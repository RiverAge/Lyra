"""LyricProvider — the abstraction every async lyric data source implements.

A provider owns three things: searching for candidates, enriching candidates
with detail, and fetching the raw lyric payload. Scoring/decision stay in
scoring.py (shared, source-agnostic); providers only produce Candidates and
raw payloads.

Why not put score_candidate/decision on the provider? They are identical
across sources (they read only normalized Candidate fields), so duplicating
them per provider would be wrong. resolve_candidates (runner.py) calls each
provider's search/detail, then scores all candidates uniformly.

All provider methods are async: Lyra is a long-lived FastAPI service, and the
original (blocking ``requests``/``urllib``) has been async-ified to
``httpx.AsyncClient``. Encryption is unchanged — only the transport layer is
async.

Note on Candidate.source vs LyricProvider.source:
  - LyricProvider.source  = the data source slug ("netease" | "qq") — used for
    choosing which provider fetches lyrics for a hit, and for the on-disk
    sidecar suffix.
  - Candidate.source      = the search-origin tag NetEase fills in
    ("search/match" | "cloudsearch:<kw>" | "song/detail"); QQ sets "qq".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from backend.lyrics.lyric_match.types import Candidate, TrackQuery


class LyricProvider(ABC):
    # subclasses set this: "netease" | "qq"
    source: str

    @abstractmethod
    async def search(self, q: TrackQuery, limit: int) -> list[Candidate]:
        """Return this source's candidates (source field filled, unscored).

        Empty list means the source has no data. Internal dedup is the
        provider's responsibility (NetEase dedups by song id across its
        /search/match + multi-/cloudsearch queries).
        """
        raise NotImplementedError

    @abstractmethod
    async def detail(self, candidates: list[Candidate]) -> list[Candidate]:
        """Enrich candidates via the source's detail API. If the source has no
        batch detail endpoint, return the list unchanged (QQ search already
        carries full fields)."""
        raise NotImplementedError

    @abstractmethod
    async def fetch_lyrics(self, candidate: Candidate) -> dict[str, Any] | None:
        """Fetch the raw lyric payload. None = no lyric / fetch failed (must
        not crash the batch). NetEase returns the /lyric/new payload verbatim;
        QQ returns {"_qrc_xml": <decrypted str>, "_provider_source": "qq"}."""
        raise NotImplementedError

    @abstractmethod
    def lyric_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Availability summary for the payload (which lyric tracks are
        present). NetEase reports lrc/yrc/tlyric/romalrc/klyric; QQ reports
        qrc. Pure function (no I/O), so it stays sync."""
        raise NotImplementedError


async def fetch_lyrics_cached(
    provider: LyricProvider, candidate: Candidate,
) -> dict[str, Any] | None:
    """fetch_lyrics + 进程级 raw payload 缓存。

    覆盖 runner / preview 两处调 fetch_lyrics 的入口（QQ 内部 find_qrc_candidate
    走 qq.py 自己 fetch_lyrics 的跨请求缓存，见 qq.py）。命中即返回缓存的 raw
    payload；miss 则回源 fetch_lyrics 再 set。TTL/语义见 payload_cache.py。

    candidate.id 为空（候选无 id）→ 不缓存、直接回源（provider 自己也会判）。
    """
    if not candidate.id:
        return None
    from backend.lyrics.lyric_match.payload_cache import get_payload_cache

    cache = get_payload_cache()
    hit = await cache.get(provider.source, candidate.id)
    if hit is not None:
        return hit
    payload = await provider.fetch_lyrics(candidate)
    await cache.set(provider.source, candidate.id, payload)
    return payload
