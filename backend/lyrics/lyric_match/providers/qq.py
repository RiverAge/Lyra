"""QQ Music provider — async, anonymous (no-login) word-synced QRC.

Two endpoints, hit DIRECTLY against QQ's official c.y.qq.com (no API
middleman — unlike the NetEase provider, which still goes through a deployed
reverse proxy). c.y.qq.com is a domestic domain, so most home/business
networks reach it directly without any proxy.

  search  : GET https://c.y.qq.com/soso/fcgi-bin/client_search_cp
            This is the old sign-less search (not musicu.fcg, which needs a
            sign and returns code 500003). Returns songid (==musicid for the
            lyric endpoint), songmid, songname, singer[], albumname, interval.
  lyrics  : GET https://c.y.qq.com/qqmusic/fcgi-bin/lyric_download.fcg
            ?version=15&miniversion=82&lrctype=4&musicid=<id>
            Returns XML wrapped in an HTML comment; the encrypted逐字 QRC is
            in the `<content><![CDATA[hex]]></content>` CDATA. contentts
            (translation) and contentroma (romanization) are separate
            encrypted payloads; only content (main逐字) is used here.

Decryption is LDDC's hand-written non-standard 3DES (crypto.tripledes_qq) —
kept verbatim (standard 3DES libraries produce garbage on QQ's variant).
The decrypted QRC XML's LyricContent is the same shape as NetEase yrc, so
converters.qrc_xml_to_ttml reuses _parse_yrc.

Why a source at all (NetEase already covers most): QQ fills NetEase gaps with
real逐字 (word-synced), not line-by-line fallback.

Transport is async via ``httpx.AsyncClient`` (Lyra is a long-lived FastAPI
service; the original ``urllib`` opener was blocking). The JSONP-strip,
placeholder detection, and decryption are unchanged — only the transport
that produces the raw response string is async.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
from typing import Any

import httpx

from backend.lyrics.lyric_match.crypto.tripledes_qq import decrypt_qrc
from backend.lyrics.lyric_match.payload_cache import get_payload_cache
from backend.lyrics.lyric_match.providers import LyricProvider
from backend.lyrics.lyric_match.scoring import make_queries
from backend.lyrics.lyric_match.types import REVIEW_SCORE, Candidate, TrackQuery

DEFAULT_TIMEOUT = 15
DEFAULT_PROXY = None  # direct connection by default; set only if QQ geo-blocks your egress IP

# QQ's own per-request sleep, DECOUPLED from the NetEase sleep. QQ's
# c.y.qq.com is far more sensitive to sustained high-frequency unauthenticated
# requests than music.163.com — a full-library rescan at sleep 0.15 (~70 QQ
# req/min sustained) trips an IP rate limit (search starts returning
# `{"message":"query error","subcode":-10003}` with totalnum=0 for hours).
# 0.8s keeps QQ under ~75 req/min for the search phase alone but, more
# importantly, spaces the burst of 5 make_queries per song enough that QQ
# stops treating a single song's search as a machine burst.
DEFAULT_QQ_SLEEP = 0.8

# QQ search recall floor. client_search_cp's `n` param is cheap (one request
# returns many), but the same song's word-synced version can rank low — limit=12
# misses it. Floor QQ's own recall to 20 without touching the global limit.
QQ_SEARCH_LIMIT = 20

_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
_LYRIC_URL = "https://c.y.qq.com/qqmusic/fcgi-bin/lyric_download.fcg"

# client_search_cp wraps the JSON in a `callback(...)` JSONP envelope when
# `format=json` is not honored; the real payload is the first {...}..last }.
_JSONP_LEFT = "callback("

# <content> may carry attributes (type/mime/timetag/filescroll) before CDATA.
_CONTENT_RE = re.compile(r'<content\b[^>]*><!\[CDATA\[([0-9A-Fa-f]*)\]\]></content>')
_CONTENTTS_RE = re.compile(r'<contentts\b[^>]*><!\[CDATA\[([0-9A-Fa-f]*)\]\]></contentts>')
_CONTENTROMA_RE = re.compile(r'<contentroma\b[^>]*><!\[CDATA\[([0-9A-Fa-f]*)\]\]></contentroma>')

# A span in QRC LyricContent looks like "(start,dur)TEXT"; capture the text
# between a closing ')' and the next '(' (or end). Used to detect the
# "暂无歌词" placeholder, which QQ returns for songs that have a QRC
# structure but no real word-synced content (4 spans spelling 暂无歌词).
_QRC_SPAN_TEXT_RE = re.compile(r'\)([^(]*)')

# The decrypted QRC XML carries the lyric data in LyricContent="..."; extract
# just that value before counting spans (the surrounding <QrcInfos> wrapper
# would otherwise pollute the span count).
_LYRIC_CONTENT_RE = re.compile(r'LyricContent="([^"]*)"')

# QQ's placeholder for "tracked but lyric-less". Decrypted QRC spells it as a
# single lyric line whose word spans are 暂/无/歌/词 (sometimes 无/歌/词). A real
# song has dozens of spans; ≤5 spans whose text is a subset of "暂无歌词" is a
# placeholder, not a real lyric.
_PLACEHOLDER_CHARS = set("暂无歌词")


def _is_placeholder_qrc(qrc_xml: str) -> bool:
    """True if the decrypted QRC is QQ's "暂无歌词" placeholder, not real lyrics."""
    if not qrc_xml or "LyricContent=" not in qrc_xml:
        return False
    m = _LYRIC_CONTENT_RE.search(qrc_xml)
    if not m:
        return False
    content = m.group(1)
    # A QRC span is "(start,dur)TEXT"; capture the text after each ')'.
    texts = _QRC_SPAN_TEXT_RE.findall(content)
    spans = [t.strip() for t in texts if t.strip()]
    if len(spans) > 5 or not spans:
        return False
    joined = "".join(spans)
    # subset of placeholder chars only (allow stray header tokens that leaked in)
    return all(c in _PLACEHOLDER_CHARS for c in joined)


def _strip_jsonp(text: str) -> str:
    """client_search_cp sometimes returns `callback({...})`; peel to the JSON."""
    stripped = text.strip()
    if stripped.startswith(_JSONP_LEFT) and stripped.endswith(")"):
        return stripped[len(_JSONP_LEFT):-1]
    # Fallback: first '{' .. last '}'
    left = stripped.find("{")
    right = stripped.rfind("}")
    if left != -1 and right != -1 and right > left:
        return stripped[left:right + 1]
    return stripped


# Re-exported (contentts/contentroma are separate encrypted payloads; only
# content (main逐字) is used by fetch_lyrics). Kept for parity with the
# reference source so future translation/roma support is a non-breaking add.
__all__ = [
    "DEFAULT_PROXY",
    "DEFAULT_QQ_SLEEP",
    "DEFAULT_TIMEOUT",
    "QQ_SEARCH_LIMIT",
    "QqProvider",
    "candidate_from_qq_song",
]


def candidate_from_qq_song(song: dict[str, Any]) -> Candidate:
    """Build an unscored Candidate from a client_search_cp song dict.

    Field map: songid→id, songname→title, singer[].name→artists,
    albumname→album, interval (seconds)→duration_ms (×1000). source is set to
    "qq" so the runner can route lyric fetch to the QQ provider (see
    runner._provider_for_candidate). raw keeps the full song dict for
    suspicious_artist_penalty (which reads raw.artists/ar — QQ raw has neither,
    so the penalty is a no-op for QQ, which is safe).
    """
    singers = song.get("singer") or []
    interval = song.get("interval")
    return Candidate(
        id=int(song.get("songid") or song.get("id") or 0),
        title=str(song.get("songname") or song.get("name") or ""),
        artists=[str(s.get("name") or "") for s in singers if isinstance(s, dict)],
        album=str(song.get("albumname") or (song.get("album") or {}).get("name") or ""),
        duration_ms=int(interval) * 1000 if isinstance(interval, (int, float)) else None,
        source="qq",
        aliases=[str(x) for x in (song.get("alias") or [])],
        raw=song,
    )


class QqProvider(LyricProvider):
    source = "qq"

    def __init__(
        self,
        proxy: str | None = DEFAULT_PROXY,
        timeout: int = DEFAULT_TIMEOUT,
        sleep: float | None = DEFAULT_QQ_SLEEP,
    ):
        self.proxy = proxy
        self.timeout = timeout
        # None (not passed) → fall back to QQ's own default, NOT the NetEase
        # sleep. This is the decoupling point: QQ never inherits NetEase's
        # aggressive 0.15s.
        self.sleep = DEFAULT_QQ_SLEEP if sleep is None else sleep
        self._client: httpx.AsyncClient | None = None
        # Per-song QRC fetch cache: avoids find_qrc_candidate probing the same
        # candidate twice (once in probe, once if chosen). Keyed by song id.
        self._qrc_cache: dict[int, dict[str, Any]] = {}

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Reference source used ssl._create_unverified_context() on the
            # urllib opener — QQ's c.y.qq.com occasionally trips on strict
            # verification. Preserve that leniency via verify=False (Lyra is a
            # private single-user deployment; the relaxed TLS is acceptable
            # and matches the original behavior — §3.9 behavior equivalence).
            self._client = httpx.AsyncClient(
                proxy=self.proxy,
                timeout=self.timeout,
                verify=False,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://y.qq.com/",
                    "Accept": "*/*",
                },
            )
        return self._client

    async def _qq_get(self, url: str) -> str:
        """GET url via httpx; return decoded text. Raises RuntimeError on HTTP/transport error."""
        client = self._ensure_client()
        try:
            resp = await client.get(url)
            data = resp.text
        except httpx.HTTPError as e:
            raise RuntimeError(f"QQ request failed: {e}") from e
        if self.sleep > 0:
            await asyncio.sleep(self.sleep)
        return data

    @staticmethod
    def _decrypt_aux(raw: str, pattern: re.Pattern, label: str) -> str:
        """从同响应里抽 contentts/contentroma hex → decrypt_qrc → 返回解密 XML。

        翻译/注音是独立加密 payload，和主 content 同一个 lyric_download 响应里。
        空 CDATA / 无该标签 / 解密失败 → 返回 ""（翻译/注音可选，不阻塞主歌词）。
        """
        m = pattern.search(raw)
        if not m:
            return ""
        hex_str = m.group(1)
        if not hex_str:
            return ""
        try:
            return decrypt_qrc(hex_str)
        except Exception:
            # 翻译/注音解密失败不影响主歌词，静默降级为空
            return ""

    async def search(self, q: TrackQuery, limit: int) -> list[Candidate]:
        # Mirror NetEase's multi-query recall: build_queries yields title+artist
        # +album permutations so a weak single-key query still finds the song.
        # Dedup by songid, first-seen wins (same as NetEase).
        # n is floored to QQ_SEARCH_LIMIT so the same song's word-synced version
        # (often ranked lower than a title-complete but QRC-less variant) is
        # recalled even when the global limit is small.
        n = max(limit, QQ_SEARCH_LIMIT)
        by_id: dict[int, Candidate] = {}
        for keywords in make_queries(q):
            if not keywords:
                continue
            params = urllib.parse.urlencode({
                "w": keywords,
                "format": "json",
                "n": n,
                "p": 1,
                "cr": 1,
                "g_tk": 5381,
                "t": 0,
                "aggr": 1,
                "lossless": 0,
                "inCharset": "utf8",
                "outCharset": "utf-8",
            })
            try:
                text = await self._qq_get(f"{_SEARCH_URL}?{params}")
                data = json.loads(_strip_jsonp(text))
            except Exception:
                continue
            songs = data.get("data", {}).get("song", {}).get("list", []) or []
            for s in songs:
                cand = candidate_from_qq_song(s)
                if cand.id:
                    by_id.setdefault(cand.id, cand)
        return list(by_id.values())

    async def detail(self, candidates: list[Candidate]) -> list[Candidate]:
        # client_search_cp already returns full fields; no separate detail API.
        return candidates

    async def fetch_lyrics(self, candidate: Candidate) -> dict[str, Any] | None:
        if not candidate.id:
            return None
        cached = self._qrc_cache.get(candidate.id)
        if cached is not None:
            return cached
        # 跨请求磁盘缓存：命中则喂给实例缓存并返回（find_qrc_candidate 走这里，
        # 让重复匹配/探测也吃跨请求缓存）。miss/过期/损坏由 cache.get 返回 None。
        cross = await get_payload_cache().get(self.source, candidate.id)
        if cross is not None:
            self._qrc_cache[candidate.id] = cross
            return cross
        url = f"{_LYRIC_URL}?version=15&miniversion=82&lrctype=4&musicid={candidate.id}"
        try:
            raw = await self._qq_get(url)
        except Exception:
            return None
        m = _CONTENT_RE.search(raw)
        if not m or not m.group(1):
            # No encrypted content — either the song has no QRC or the endpoint
            # shape changed. Return a marker so lyric_summary reports it.
            payload: dict[str, Any] = {
                "_qrc_xml": "",
                "_qrc_ts_xml": "",
                "_qrc_roma_xml": "",
                "_provider_source": "qq",
                "_qrc_status": "no_content",
            }
            self._qrc_cache[candidate.id] = payload
            await get_payload_cache().set(self.source, candidate.id, payload)
            return payload
        hex_str = m.group(1)
        try:
            qrc_xml = decrypt_qrc(hex_str)
        except Exception as e:
            # Don't cache decrypt errors — allow a retry on the same id later.
            return {
                "_qrc_xml": "",
                "_qrc_ts_xml": "",
                "_qrc_roma_xml": "",
                "_provider_source": "qq",
                "_qrc_status": f"decrypt_error: {type(e).__name__}: {e}",
            }
        if _is_placeholder_qrc(qrc_xml):
            # QQ returns a structured "暂无歌词" placeholder for songs tracked
            # in its DB but lacking real word-synced content. Mark it so the
            # fallback skips this candidate (find_qrc_candidate's status check
            # rejects non-empty _qrc_status) — we keep probing the next QQ
            # candidate instead of landing an empty 3-span TTML. Cached so a
            # repeat fetch is free.
            payload = {
                "_qrc_xml": "",
                "_qrc_ts_xml": "",
                "_qrc_roma_xml": "",
                "_provider_source": "qq",
                "_qrc_status": "placeholder",
            }
            self._qrc_cache[candidate.id] = payload
            await get_payload_cache().set(self.source, candidate.id, payload)
            return payload
        payload = {"_qrc_xml": qrc_xml, "_provider_source": "qq"}
        # 同响应里抽翻译(contentts)/注音(contentroma)：独立加密 payload，
        # 复用 decrypt_qrc。空/失败留空字符串，不阻塞主歌词（翻译/注音是可选）。
        payload["_qrc_ts_xml"] = self._decrypt_aux(raw, _CONTENTTS_RE, "contentts")
        payload["_qrc_roma_xml"] = self._decrypt_aux(raw, _CONTENTROMA_RE, "contentroma")
        self._qrc_cache[candidate.id] = payload
        await get_payload_cache().set(self.source, candidate.id, payload)
        return payload

    async def find_qrc_candidate(
        self, qq_candidates: list[Candidate],
    ) -> tuple[Candidate | None, dict[str, Any] | None]:
        """Probe QQ candidates (score-desc) for the first with a real QRC.

        Used by runner's QRC fallback: when the NetEase best has no word-synced
        yrc, search the QQ pool for a candidate that actually carries word-synced
        QRC. Probes in score-descending order, stops at first hit. Only probes
        candidates scoring >= REVIEW_SCORE (plausible same-song matches), capped
        at max_probe to bound request amplification. Hits the fetch cache so
        candidates already fetched in the main path are free.
        """
        max_probe = 3
        probed = 0
        for c in sorted(qq_candidates, key=lambda x: x.score, reverse=True):
            if probed >= max_probe:
                break
            if c.score < REVIEW_SCORE:
                break
            probed += 1
            payload = await self.fetch_lyrics(c)
            if not payload:
                continue
            xml = payload.get("_qrc_xml") or ""
            if xml and "LyricContent=" in xml and not payload.get("_qrc_status"):
                return c, payload
        return None, None

    def lyric_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        qrc_xml = payload.get("_qrc_xml") or ""
        status = payload.get("_qrc_status", "ok")
        has_qrc = bool(qrc_xml and "LyricContent=" in qrc_xml)
        return {
            "qrc": has_qrc,
            "qrc_status": status,
        }

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient (idempotent)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
