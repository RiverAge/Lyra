"""NetEase provider — async, talks directly to music.163.com via weapi.

NeteaseClient wraps a WeapiSession (crypto/weapi_netease.py, now
httpx.AsyncClient-backed) and POSTs weapi-encrypted payloads straight to
music.163.com — no deployed reverse proxy. The candidate_from_*_song factories
are lifted verbatim from the pre-split netease_match_lyrics.py (zero behavior
change); NeteaseProvider implements the async LyricProvider with a
search+detail split so the runner can score uniformly across providers.

Direct weapi endpoints (verified to return byte-identical yrc vs. the old
reverse proxy for Lovestoned - Rising Girl, id 4164317):
  search   : /weapi/cloudsearch/pc  (replaces reverse-proxy /cloudsearch)
  detail   : /weapi/v3/song/detail  (replaces /song/detail)
  lyric    : /weapi/song/lyric/v1    (replaces /lyric/new; returns yrc)

Note: the reverse proxy's /search/match (title+album+artist+duration+md5
pre-match) has no music.163.com native equivalent — direct mode uses
/weapi/cloudsearch/pc with make_queries multi-key recall + local scoring
instead.

All client/provider methods are async (transport layer only; encryption via
weapi_encrypt is unchanged).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from backend.lyrics.lyric_match.crypto.weapi_netease import WeapiSession
from backend.lyrics.lyric_match.providers import LyricProvider
from backend.lyrics.lyric_match.scoring import make_queries
from backend.lyrics.lyric_match.types import Candidate, TrackQuery

DEFAULT_TIMEOUT = 15


class NeteaseClient:
    def __init__(
        self,
        cookie: str | None = None,
        proxy: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        sleep: float = 0.15,
    ):
        self.cookie = cookie
        self.timeout = timeout
        self.sleep = sleep
        self._session = WeapiSession(cookie=cookie, proxy=proxy, timeout=timeout, sleep=sleep)

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """POST params (weapi-encrypted) to music.163.com<path>; return JSON."""
        return await self._session.post_weapi(path, params)

    async def search_match(self, q: TrackQuery) -> list[Candidate]:
        # music.163.com has no native /search/match (that was the reverse
        # proxy's title+album+artist+duration+md5 pre-match). Direct mode
        # approximates it with a single cloudsearch by "{title} {artist}",
        # keeping the "search/match" source tag so the result marks this
        # dedicated first-pass query path distinctly from the multi-query
        # cloudsearch loop below.
        if not (q.title and q.artist and q.duration is not None):
            return []
        data = await self.get(
            "/weapi/cloudsearch/pc",
            {
                "s": f"{q.title} {q.artist}",
                "type": 1,
                "limit": 12,
                "offset": 0,
            },
        )
        songs = data.get("result", {}).get("songs", []) or []
        return [candidate_from_search_song(s, "search/match") for s in songs]

    async def cloudsearch(self, keywords: str, limit: int) -> list[Candidate]:
        data = await self.get(
            "/weapi/cloudsearch/pc",
            {
                "s": keywords,
                "type": 1,
                "limit": limit,
                "offset": 0,
            },
        )
        songs = data.get("result", {}).get("songs", []) or []
        return [candidate_from_search_song(s, f"cloudsearch:{keywords}") for s in songs]

    async def song_detail(self, ids: Iterable[int]) -> list[Candidate]:
        unique_ids = [i for i in dict.fromkeys(ids) if i]
        if not unique_ids:
            return []
        data = await self.get(
            "/weapi/v3/song/detail",
            {"c": json.dumps([{"id": i} for i in unique_ids]), "v": "v1"},
        )
        songs = data.get("songs", []) or []
        privileges = {
            int(p.get("id") or 0): p
            for p in (data.get("privileges", []) or [])
            if isinstance(p, dict)
        }
        return [
            candidate_from_detail_song(s, "song/detail", privileges.get(int(s.get("id") or 0)))
            for s in songs
        ]

    async def lyric_new(self, song_id: int) -> dict[str, Any]:
        return await self.get(
            "/weapi/song/lyric/v1",
            {"id": song_id, "lv": -1, "tv": -1, "kv": -1, "yv": -1},
        )

    async def close(self) -> None:
        await self._session.close()


def candidate_from_search_song(song: dict[str, Any], source: str) -> Candidate:
    album = song.get("album") or song.get("al") or {}
    artists = song.get("artists") or song.get("ar") or []
    duration = song.get("duration", song.get("dt"))
    return Candidate(
        id=int(song.get("id") or 0),
        title=str(song.get("name") or ""),
        artists=[str(a.get("name") or "") for a in artists if isinstance(a, dict)],
        album=str(album.get("name") or ""),
        duration_ms=int(duration) if isinstance(duration, (int, float)) else None,
        source=source,
        aliases=[str(x) for x in (song.get("alias") or song.get("alia") or [])],
        copyright=int(song["copyright"]) if isinstance(song.get("copyright"), int) else None,
        status=int(song["status"]) if isinstance(song.get("status"), int) else None,
        privilege_st=(
            int(song["privilege"]["st"])
            if isinstance(song.get("privilege"), dict)
            and isinstance(song["privilege"].get("st"), int)
            else None
        ),
        privilege_pl=(
            int(song["privilege"]["pl"])
            if isinstance(song.get("privilege"), dict)
            and isinstance(song["privilege"].get("pl"), int)
            else None
        ),
        raw=song,
    )


def candidate_from_detail_song(
    song: dict[str, Any],
    source: str,
    privilege: dict[str, Any] | None = None,
) -> Candidate:
    album = song.get("al") or song.get("album") or {}
    artists = song.get("ar") or song.get("artists") or []
    return Candidate(
        id=int(song.get("id") or 0),
        title=str(song.get("name") or ""),
        artists=[str(a.get("name") or "") for a in artists if isinstance(a, dict)],
        album=str(album.get("name") or ""),
        duration_ms=int(song["dt"]) if isinstance(song.get("dt"), (int, float)) else None,
        source=source,
        aliases=[str(x) for x in (song.get("alia") or song.get("alias") or [])],
        copyright=int(song["copyright"]) if isinstance(song.get("copyright"), int) else None,
        status=int(song["st"]) if isinstance(song.get("st"), int) else None,
        privilege_st=(
            int(privilege["st"])
            if isinstance(privilege, dict) and isinstance(privilege.get("st"), int)
            else None
        ),
        privilege_pl=(
            int(privilege["pl"])
            if isinstance(privilege, dict) and isinstance(privilege.get("pl"), int)
            else None
        ),
        raw=song,
    )


class NeteaseProvider(LyricProvider):
    source = "netease"

    def __init__(
        self,
        cookie: str | None = None,
        proxy: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        sleep: float = 0.15,
    ):
        self.client = NeteaseClient(cookie, proxy, timeout, sleep)

    async def search(self, q: TrackQuery, limit: int) -> list[Candidate]:
        # Mirrors the old resolve_candidates NetEase search half:
        # /search/match first (needs title+artist+duration), then multiple
        # /cloudsearch queries; dedup by song id, first-seen wins.
        by_id: dict[int, Candidate] = {}
        for c in await self.client.search_match(q):
            if c.id:
                by_id.setdefault(c.id, c)
        for keywords in make_queries(q):
            for c in await self.client.cloudsearch(keywords, limit):
                if c.id:
                    by_id.setdefault(c.id, c)
        return list(by_id.values())

    async def detail(self, candidates: list[Candidate]) -> list[Candidate]:
        # Mirrors the old resolve_candidates detail half: batch /song/detail,
        # preserve the search-origin source tag (prior_source) so output is
        # byte-identical to the pre-split behavior.
        by_id: dict[int, Candidate] = {c.id: c for c in candidates if c.id}
        if not by_id:
            return []
        details = await self.client.song_detail(by_id.keys())
        for detail in details:
            if detail.id:
                prior = by_id.get(detail.id)
                prior_source = prior.source if prior is not None else detail.source
                detail.source = prior_source
                by_id[detail.id] = detail
        return list(by_id.values())

    async def fetch_lyrics(self, candidate: Candidate) -> dict[str, Any] | None:
        # /lyric/new payload returned verbatim; lyrics_io.converters consume it.
        return await self.client.lyric_new(candidate.id)

    def lyric_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        def has_lyric(name: str) -> bool:
            value = payload.get(name) or {}
            return bool(str(value.get("lyric") or "").strip())

        return {
            "lrc": has_lyric("lrc"),
            "yrc": has_lyric("yrc"),
            "tlyric": has_lyric("tlyric"),
            "romalrc": has_lyric("romalrc"),
            "klyric": has_lyric("klyric"),
            "code": payload.get("code"),
        }

    async def close(self) -> None:
        await self.client.close()
