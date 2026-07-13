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
