# ruff: noqa: UP009, I001, E501 - 逐字从 AppleMusicDecrypt tools/lyric_match 搬迁
# （仅改 import 路径 lyric_match→backend.lyrics.lyric_match）；风格保留原码
# -*- coding: utf-8 -*-
"""Scoring / decision logic — source-agnostic.

Pure functions. Reads only TrackQuery / Candidate fields (title, artists, album,
duration, aliases, version words). Works for any provider (NetEase, QQ) because
candidates are normalized to the Candidate dataclass before scoring. No HTTP,
no provider imports.

The multi-source `resolve_candidates` lives in runner.py (it needs the
LyricProvider interface); this module only owns the per-candidate scoring and
the accept/review/reject decision.
"""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

from backend.lyrics.lyric_match.types import (
    AUTO_ACCEPT_SCORE,
    REVIEW_SCORE,
    MIN_ACCEPT_GAP,
    Candidate,
    TrackQuery,
)

CREDIT_PREFIXES = (
    "作词",
    "作詞",
    "作曲",
    "编曲",
    "編曲",
    "制作人",
    "製作人",
    "和声",
    "和聲",
    "吉他",
    "贝斯",
    "貝斯",
    "鼓",
    "录音",
    "錄音",
    "混音",
    "母带",
    "母帶",
    "纯音乐",
    "純音樂",
    "演唱",
    "歌手",
    "singer",
    "artist",
)

VERSION_WORDS = {
    "live",
    "remix",
    "mix",
    "demo",
    "cover",
    "instrumental",
    "acoustic",
    "piano",
    "rock",
    "r&b",
    "伴奏",
    "翻唱",
    "原唱",
    "现场",
    "演唱会",
    "钢琴",
    "吉他",
    "女声",
    "女生",
    "男声",
    "深情",
    "伤感",
    "抖音",
    "片段",
    "剪辑",
    "加速",
    "降调",
    "升调",
    "dj",
}

DROP_TITLE_WORDS = {
    "official",
    "audio",
    "music",
    "video",
    "mv",
    "版",
}

ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|，|、|/|／|;|；|&|＆|\+| x | X |×| feat\.?| ft\.?| featuring | with |・|·|•)\s*",
    re.IGNORECASE,
)

# 合集/精选集占位艺人名：本地 tag 用它表示"群星合辑"，并非真实艺人。
# 比对艺人时若本地是占位符，视为无有效艺人信息，跳过 artist 评分，
# 由 album + duration 决定（典型场景：天赐的声音等合辑被本地标成"群星"）。
COMPILATION_ARTIST_PLACEHOLDERS = {
    "群星",
    "variousartists",
    "various",
    "va",
    "unknown",
    "未知",
    "未知艺人",
    "佚名",
    "misc",
}

# 专辑名常见后缀标记：本地 tag 常带 " - Single"/" - EP" 等，网易原始专辑名没有。
# 比对 album 时先从两侧剥离这些词，避免 "xxx - Single" vs "xxx" 被判 mismatch。
ALBUM_SUFFIX_WORDS = {
    "single",
    "ep",
    "lp",
}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = value.replace("’", "'").replace("`", "'")
    value = re.sub(r"\([^)]*\)|（[^）]*）|\[[^\]]*]|\{[^}]*}", " ", value)
    value = re.sub(r"[\-_:：~～|｜]+", " ", value)
    value = re.sub(r"[^\w぀-ヿ㐀-鿿가-힯]+", " ", value)
    words = [w for w in value.split() if w and w not in DROP_TITLE_WORDS]
    return " ".join(words)


def compact_text(value: str) -> str:
    return normalize_text(value).replace(" ", "")


def normalize_album(value: str) -> str:
    """专辑名规范化：复用 compact_text 折叠逻辑，再剥离 single/ep/lp 等后缀标记词。

    本地 tag 常带 "xxx - Single"/"xxx - EP"，网易原始专辑名只有 "xxx"，
    直接 ratio 会被后缀稀释。先把这些后缀词删掉再比对。
    """
    norm = compact_text(value)
    for suffix in ALBUM_SUFFIX_WORDS:
        if norm.endswith(suffix) and len(norm) > len(suffix):
            norm = norm[: -len(suffix)]
    return norm


def album_ratio(a: str, b: str) -> float:
    a_norm = normalize_album(a)
    b_norm = normalize_album(b)
    if not a_norm and not b_norm:
        return 1.0
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def is_compilation_placeholder(value: str) -> bool:
    return compact_text(value) in COMPILATION_ARTIST_PLACEHOLDERS


def ratio(a: str, b: str) -> float:
    a_norm = compact_text(a)
    b_norm = compact_text(b)
    if not a_norm and not b_norm:
        return 1.0
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def split_artists(value: str) -> list[str]:
    if not value:
        return []
    parts = ARTIST_SPLIT_RE.split(value)
    out: list[str] = []
    for part in parts:
        for clean in artist_variants(part):
            if clean and clean not in out:
                out.append(clean)
    return out


def normalize_artist(value: str) -> str:
    value = normalize_text(value)
    value = re.sub(r"\b(?:feat|ft|featuring|with)\b", " ", value)
    return value.strip()


def artist_variants(value: str) -> list[str]:
    raw = unicodedata.normalize("NFKC", value or "")
    variants: list[str] = []

    def add(item: str) -> None:
        normalized = normalize_artist(item)
        if normalized and normalized not in variants:
            variants.append(normalized)

    add(raw)
    for match in re.finditer(r"\(([^)]*)\)|（([^）]*)）|\[([^\]]*)]|\{([^}]*)}", raw):
        for group in match.groups():
            if group:
                add(group)
    return variants


def detect_version_words(*values: str) -> set[str]:
    # Keep bracket contents here. normalize_text intentionally removes them for
    # title identity matching, but version markers often live in parentheses.
    joined = unicodedata.normalize("NFKC", " ".join(values or "")).lower()
    return {w for w in VERSION_WORDS if w in joined}


def best_title_score(q: TrackQuery, c: Candidate) -> tuple[float, str]:
    values = [c.title] + c.aliases
    best = max((ratio(q.title, v), v) for v in values if v) if values else (0.0, "")
    r, matched = best
    if r >= 0.995:
        return 36.0, f"title exact ({matched})"
    if r >= 0.92:
        return 31.0, f"title close {r:.2f} ({matched})"
    if r >= 0.82:
        return 22.0, f"title fuzzy {r:.2f} ({matched})"
    if compact_text(q.title) and compact_text(q.title) in compact_text(matched):
        return 18.0, f"title contained ({matched})"
    return max(0.0, 18.0 * r), f"title weak {r:.2f} ({matched})"


def artist_score(query_artists: list[str], candidate_artists: list[str]) -> tuple[float, str]:
    if not query_artists:
        return 0.0, "no query artist"
    # 本地艺人全是合集占位符(群星/Various Artists…)时，本地 tag 无有效艺人信息，
    # artist 比对无意义；返回中性分(不奖不罚)，由 album + duration 决定。
    if query_artists and all(is_compilation_placeholder(a) for a in query_artists):
        return 0.0, "query artist is compilation placeholder"
    if not candidate_artists:
        return -12.0, "candidate has no artist"

    candidate_variants: list[str] = []
    for artist in candidate_artists:
        for variant in artist_variants(artist):
            if variant and variant not in candidate_variants:
                candidate_variants.append(variant)
        for part in ARTIST_SPLIT_RE.split(artist):
            for variant in artist_variants(part):
                if variant and variant not in candidate_variants:
                    candidate_variants.append(variant)
    if not candidate_variants:
        return -12.0, "candidate has no artist"

    best_scores: list[float] = []
    matched: list[str] = []
    for qa in query_artists:
        best = max((artist_ratio(qa, ca), ca) for ca in candidate_variants)
        best_scores.append(best[0])
        matched.append(best[1])

    avg_best = sum(best_scores) / len(best_scores)
    exact_count = sum(1 for s in best_scores if s >= 0.98)
    if exact_count == len(query_artists):
        return 28.0, "artist exact"
    if avg_best >= 0.90:
        return 24.0, f"artist close {avg_best:.2f}"
    if avg_best >= 0.78:
        return 16.0, f"artist fuzzy {avg_best:.2f}"
    return -18.0, f"artist mismatch {avg_best:.2f} ({', '.join(matched)})"


def artist_ratio(left: str, right: str) -> float:
    left_compact = left.replace(" ", "")
    right_compact = right.replace(" ", "")
    if left_compact and right_compact:
        shorter = min(len(left_compact), len(right_compact))
        if shorter >= 2 and (left_compact in right_compact or right_compact in left_compact):
            return 1.0
    return ratio(left_compact, right_compact)


def album_score(query_album: str, candidate_album: str) -> tuple[float, str]:
    if not query_album:
        return 0.0, "no query album"
    raw = ratio(query_album, candidate_album)
    r = album_ratio(query_album, candidate_album)
    norm_tag = " (norm)" if r != raw else ""
    if r >= 0.98:
        return 16.0, f"album exact{norm_tag}"
    if r >= 0.88:
        return 12.0, f"album close {r:.2f}{norm_tag}"
    if r >= 0.72:
        return 7.0, f"album fuzzy {r:.2f}{norm_tag}"
    return -8.0, f"album mismatch {r:.2f}{norm_tag}"


def duration_score(query_duration: float | None, candidate_duration: float | None) -> tuple[float, str]:
    if query_duration is None or candidate_duration is None:
        return 0.0, "no duration"
    delta = abs(query_duration - candidate_duration)
    if delta <= 1.5:
        return 20.0, f"duration exact {delta:.1f}s"
    if delta <= 3.0:
        return 17.0, f"duration close {delta:.1f}s"
    if delta <= 6.0:
        return 11.0, f"duration ok {delta:.1f}s"
    if delta <= 12.0:
        return 4.0, f"duration loose {delta:.1f}s"
    return -24.0, f"duration mismatch {delta:.1f}s"


def version_penalty(q: TrackQuery, c: Candidate) -> tuple[float, str | None]:
    q_words = detect_version_words(q.title, q.album)
    c_words = detect_version_words(c.title, c.album, " ".join(c.aliases))
    extra = c_words - q_words
    if not extra:
        return 0.0, None
    severe = extra & {
        "cover",
        "翻唱",
        "原唱",
        "live",
        "现场",
        "remix",
        "dj",
        "伴奏",
        "instrumental",
        "piano",
        "钢琴",
        "女声",
        "女生",
        "男声",
    }
    penalty = -18.0 if severe else -8.0
    return penalty, f"candidate has extra version words: {', '.join(sorted(extra))}"


def suspicious_artist_penalty(c: Candidate) -> tuple[float, str | None]:
    raw_artists = c.raw.get("artists") or c.raw.get("ar") or []
    if not raw_artists:
        return 0.0, None
    zero_named = [
        str(a.get("name") or "")
        for a in raw_artists
        if isinstance(a, dict) and int(a.get("id") or 0) == 0 and str(a.get("name") or "").strip()
    ]
    if zero_named:
        return -10.0, "artist id is 0 for " + ", ".join(zero_named[:3])
    return 0.0, None


def score_candidate(q: TrackQuery, c: Candidate) -> Candidate:
    query_artists = split_artists(q.artist)
    candidate_artists = [a for a in c.artists if normalize_artist(a)]

    title_part = best_title_score(q, c)
    artist_part = artist_score(query_artists, candidate_artists)
    album_part = album_score(q.album, c.album)
    duration_part = duration_score(q.duration, c.duration_s)
    parts = [title_part, artist_part, album_part, duration_part]

    score = 0.0
    reasons: list[str] = []
    penalties: list[str] = []
    for value, reason in parts:
        score += value
        reasons.append(reason)

    for value, reason in (version_penalty(q, c), suspicious_artist_penalty(c)):  # type: ignore[assignment]
        score += value
        if reason:
            penalties.append(reason)

    if strong_non_artist_metadata(q, c) and score < 84.0:
        # 本地艺人是合集占位符(群星…)时，本地无有效艺人信息，title/album/duration
        # 三强已足够判定同一首歌，提升到 accept 线而非 review 线。
        query_artists_placeholder = all(
            is_compilation_placeholder(a) for a in split_artists(q.artist)
        ) if q.artist else False
        floor = 86.0 if query_artists_placeholder else 84.0
        score = max(score, floor)
        if query_artists_placeholder:
            reasons.append("strong title/album/duration with placeholder artist -> accept")
            c.force_accept = True
        else:
            reasons.append("strong title/album/duration metadata despite artist mismatch")

    c.score = round(max(0.0, min(100.0, score)), 2)
    c.reasons = reasons
    c.penalties = penalties
    return c


def strong_non_artist_metadata(q: TrackQuery, c: Candidate) -> bool:
    if not (q.title and q.album and q.duration is not None and c.duration_s is not None):
        return False
    title_values = [c.title] + c.aliases
    title_match = max((ratio(q.title, v) for v in title_values if v), default=0.0) >= 0.98
    album_match = album_ratio(q.album, c.album) >= 0.88
    duration_match = abs(q.duration - c.duration_s) <= 2.0
    return title_match and album_match and duration_match


def make_queries(q: TrackQuery) -> list[str]:
    parts = []
    if q.title and q.artist and q.album:
        parts.append(f"{q.title} {q.artist} {q.album}")
        parts.append(f"{q.title} {q.album} {q.artist}")
    if q.title and q.artist:
        parts.append(f"{q.title} {q.artist}")
    if q.title and q.album:
        parts.append(f"{q.title} {q.album}")
    if q.title:
        parts.append(q.title)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in parts:
        key = normalize_text(item)
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def decision(candidates: list[Candidate]) -> tuple[str, str]:
    if not candidates:
        return "not_found", "no candidates"
    top = candidates[0]
    second = candidates[1].score if len(candidates) > 1 else -math.inf
    gap = top.score - second
    if top.score >= AUTO_ACCEPT_SCORE and gap >= MIN_ACCEPT_GAP:
        return "accept", f"score {top.score:.1f}, gap {gap:.1f}"
    # 占位符艺人提升路径：本地无艺人信息，title/album/duration 三强即可信，
    # 同分多候选(同一首歌多个网易条目)gap=0 也放行。
    if top.force_accept and top.score >= AUTO_ACCEPT_SCORE:
        return "accept", f"score {top.score:.1f}, gap {gap:.1f} (placeholder artist)"
    if top.score >= REVIEW_SCORE:
        if gap < MIN_ACCEPT_GAP:
            return "review", f"ambiguous: score {top.score:.1f}, gap {gap:.1f}"
        return "review", f"medium confidence: score {top.score:.1f}"
    return "reject", f"low confidence: score {top.score:.1f}"
