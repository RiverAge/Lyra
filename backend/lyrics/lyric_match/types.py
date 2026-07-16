# ruff: noqa: UP009 - 逐字从 AppleMusicDecrypt tools/lyric_match 搬迁，保留编码声明
# -*- coding: utf-8 -*-
"""Shared data types and scoring thresholds for lyric matching.

Pure data + constants only; no logic. Depended on by scoring, providers,
lyrics_io, runner. No imports from other lyric_match submodules (leaf module).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---- scoring thresholds (shared by scoring + runner) ----
AUTO_ACCEPT_SCORE = 86.0
REVIEW_SCORE = 74.0
MIN_ACCEPT_GAP = 6.0

# ---- audio extensions scanned by --dir (shared by CLI + lyrics_io) ----
DEFAULT_EXTENSIONS = (".m4a", ".mp4", ".m4p", ".flac", ".mp3")


@dataclass
class TrackQuery:
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: float | None = None
    md5: str = ""
    path: Path | None = None


@dataclass
class Candidate:
    id: int
    title: str
    artists: list[str]
    album: str
    duration_ms: int | None
    source: str
    aliases: list[str] = field(default_factory=list)
    copyright: int | None = None
    status: int | None = None
    privilege_st: int | None = None
    privilege_pl: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    force_accept: bool = False

    @property
    def duration_s(self) -> float | None:
        if self.duration_ms is None:
            return None
        return self.duration_ms / 1000.0

    @property
    def playable(self) -> bool | None:
        if self.privilege_st is not None:
            return self.privilege_st >= 0 and (self.privilege_pl or 0) > 0
        if self.status is not None:
            return self.status >= 0
        return None


def candidate_to_dict(c: Candidate) -> dict[str, Any]:
    return {
        "id": c.id,
        "score": c.score,
        "title": c.title,
        "artists": c.artists,
        "album": c.album,
        "duration": c.duration_s,
        "source": _normalize_source(c.source),
        "playable": c.playable,
        "copyright": c.copyright,
        "status": c.status,
        "privilege_st": c.privilege_st,
        "privilege_pl": c.privilege_pl,
        "aliases": c.aliases,
        "reasons": c.reasons,
        "penalties": c.penalties,
    }


def _normalize_source(raw: str) -> str:
    """序列化边界规整：把 Candidate.source 转成干净 provider slug。

    内存中的 Candidate.source 保留 NetEase 搜索接口 tag（search/match /
    cloudsearch:kw / song/detail）不动——runner._provider_for_candidate 按
    == "qq" 路由，脏值不影响。只在输出 dict 时规整成 slug 供前端展示，
    避免 "search/match人生" 这类接口路径泄漏到 UI。
    白名单：已知 slug 原样；未知值一律归 "netease"（非 qq 即 NetEase 路由）。
    """
    if raw in ("netease", "qq"):
        return raw
    return "netease"


def query_to_dict(q: TrackQuery) -> dict[str, Any]:
    return {
        "title": q.title,
        "artist": q.artist,
        "album": q.album,
        "duration": q.duration,
        "md5": q.md5,
    }
