"""Filesystem layer for lyric matching — sidecar paths, audio query, payload compare.

Reads audio metadata (mutagen, lazily imported inside the per-format readers),
computes the mirrored on-disk sidecar paths, compares embedded vs. matched
lyrics, and writes raw/raw+TTML payloads. Source knowledge is parameterized
via `lyric_source_suffix` so the same functions serve NetEase (`-netease.ttml`)
and QQ (`-qq.ttml`) without behavior forks.

The default suffix is "netease" so existing key names (`netease_raw_path`,
`netease_ttml_path`) and on-disk layout are byte-identical to the pre-split
script — that is the zero-regression contract for stage 1.

The CLI batch-only helpers (scan_cache / JSONL / progress_metrics /
parse_extensions / format_duration / parse_decision_set) are NOT carried into
Lyra — §3.5 anti-over-design; the route layer has no use for them.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from backend.lyrics.lyric_match.converters import payload_to_ttml
from backend.lyrics.lyric_match.scoring import CREDIT_PREFIXES, normalize_text
from backend.lyrics.lyric_match.types import TrackQuery

# ---- audio metadata reading (mutagen lazily imported) ----

def read_mp4_query(path: Path, with_md5: bool) -> TrackQuery:
    try:
        import mutagen.mp4
    except ImportError as e:
        raise RuntimeError("mutagen is required for file metadata extraction") from e

    audio = mutagen.mp4.MP4(path)
    tags: Any = audio.tags or {}

    def first(tag: str) -> str:
        value = tags.get(tag)
        if not value:
            return ""
        item = value[0]
        if isinstance(item, bytes):
            return item.decode("utf-8", errors="replace")
        return str(item)

    duration = float(audio.info.length) if audio.info and audio.info.length else None
    md5 = file_md5(path) if with_md5 else ""
    return TrackQuery(
        title=first("\xa9nam") or path.stem,
        artist=first("\xa9ART"),
        album=first("\xa9alb"),
        duration=duration,
        md5=md5,
        path=path,
    )


def read_mp4_lyric_texts(path: Path) -> list[dict[str, str]]:
    try:
        import mutagen.mp4
    except ImportError as e:
        raise RuntimeError("mutagen is required for embedded lyric extraction") from e

    audio = mutagen.mp4.MP4(path)
    tags: Any = audio.tags or {}
    entries: list[dict[str, str]] = []
    for tag, value in tags.items():
        tag_lower = tag.lower()
        if tag != "\xa9lyr" and not (
            ("lyrics" in tag_lower or "yrc" in tag_lower)
            and "lyricist" not in tag_lower
        ):
            continue

        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, bytes):
                text = item.decode("utf-8", errors="replace")
            else:
                text = str(item)
            if text.strip():
                entries.append(
                    {
                        "tag": tag,
                        "lang": detect_embedded_lang(text),
                        "text": text,
                    }
                )
    return entries


def read_flac_query(path: Path, with_md5: bool) -> TrackQuery:
    try:
        import mutagen.flac
    except ImportError as e:
        raise RuntimeError("mutagen is required for file metadata extraction") from e

    audio = mutagen.flac.FLAC(path)
    tags: Any = audio.tags or {}

    def first(tag: str) -> str:
        value = tags.get(tag)
        if not value:
            return ""
        item = value[0]
        if isinstance(item, bytes):
            return item.decode("utf-8", errors="replace")
        return str(item)

    duration = float(audio.info.length) if audio.info and audio.info.length else None
    md5 = file_md5(path) if with_md5 else ""
    return TrackQuery(
        title=first("title") or path.stem,
        artist=first("artist"),
        album=first("album"),
        duration=duration,
        md5=md5,
        path=path,
    )


def read_flac_lyric_texts(path: Path) -> list[dict[str, str]]:
    try:
        import mutagen.flac
    except ImportError as e:
        raise RuntimeError("mutagen is required for embedded lyric extraction") from e

    audio = mutagen.flac.FLAC(path)
    tags: Any = audio.tags or {}
    entries: list[dict[str, str]] = []
    # Vorbis comment 键大小写不敏感; mutagen 规范化为小写。
    # 收集 lyrics 字段及任何含 lyrics/yrc(不含 lyricist) 的字段, 对齐 MP4 规则。
    for tag, value in tags.items():
        tag_lower = tag.lower()
        if "lyrics" not in tag_lower and "yrc" not in tag_lower:
            continue
        if "lyricist" in tag_lower:
            continue

        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, bytes):
                text = item.decode("utf-8", errors="replace")
            else:
                text = str(item)
            if text.strip():
                entries.append(
                    {
                        "tag": tag,
                        "lang": detect_embedded_lang(text),
                        "text": text,
                    }
                )
    return entries


def read_mp3_query(path: Path, with_md5: bool) -> TrackQuery:
    try:
        import mutagen.mp3
    except ImportError as e:
        raise RuntimeError("mutagen is required for file metadata extraction") from e

    audio = mutagen.mp3.MP3(path)
    tags: Any = audio.tags or {}

    def first(frame_id: str) -> str:
        frame = tags.get(frame_id)
        if not frame:
            return ""
        text_list = getattr(frame, "text", None)
        if not text_list:
            return ""
        item = text_list[0]
        if isinstance(item, bytes):
            return item.decode("utf-8", errors="replace")
        return str(item)

    duration = float(audio.info.length) if audio.info and audio.info.length else None
    md5 = file_md5(path) if with_md5 else ""
    return TrackQuery(
        title=first("TIT2") or path.stem,
        artist=first("TPE1"),
        album=first("TALB"),
        duration=duration,
        md5=md5,
        path=path,
    )


def read_mp3_lyric_texts(path: Path) -> list[dict[str, str]]:
    try:
        import mutagen.mp3
    except ImportError as e:
        raise RuntimeError("mutagen is required for embedded lyric extraction") from e

    audio = mutagen.mp3.MP3(path)
    tags: Any = audio.tags or {}
    entries: list[dict[str, str]] = []
    # USLT(未同步歌词)帧: .lang(3字符ISO-639-2) .desc .text。可有多语言多帧。
    for frame in tags.getall("USLT"):
        text = getattr(frame, "text", "") or ""
        if not text.strip():
            continue
        lang = getattr(frame, "lang", "") or ""
        desc = getattr(frame, "desc", "") or ""
        entries.append(
            {
                "tag": f"USLT:{lang}:{desc}",
                "lang": lang or detect_embedded_lang(text),
                "text": text,
            }
        )
    return entries


def read_audio_query(path: Path, with_md5: bool) -> TrackQuery:
    suffix = path.suffix.lower()
    if suffix in (".m4a", ".mp4", ".m4p"):
        return read_mp4_query(path, with_md5)
    if suffix == ".flac":
        return read_flac_query(path, with_md5)
    if suffix == ".mp3":
        return read_mp3_query(path, with_md5)
    raise ValueError(f"unsupported audio extension: {path.suffix}")


def read_audio_lyric_texts(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix in (".m4a", ".mp4", ".m4p"):
        return read_mp4_lyric_texts(path)
    if suffix == ".flac":
        return read_flac_lyric_texts(path)
    if suffix == ".mp3":
        return read_mp3_lyric_texts(path)
    raise ValueError(f"unsupported audio extension: {path.suffix}")


def file_has_embedded_lyrics(path: Path) -> bool:
    try:
        return bool(read_audio_lyric_texts(path))
    except Exception:
        return False


def detect_embedded_lang(text: str) -> str:
    first = text.strip().splitlines()[0] if text.strip() else ""
    match = re.match(r"\[lang:\s*([^]]+)]", first, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def pick_main_embedded_lyrics(entries: list[dict[str, str]]) -> dict[str, str] | None:
    if not entries:
        return None
    for entry in entries:
        lang = entry.get("lang", "").replace(" ", "").lower()
        if lang.startswith("ori-") or lang == "ori":
            return entry
    return entries[0]


def file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main_lyric_text(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (source_key, text) of the first non-empty lrc/yrc track.

    Used by compare_embedded to extract the matched lyric text for similarity.
    Provider-agnostic (reads lrc/yrc keys, which QQ payloads do not carry — QQ
    comparison is handled separately when stage 2 lands).
    """
    for key in ("lrc", "yrc"):
        value = payload.get(key) or {}
        text = str(value.get("lyric") or "")
        if text.strip():
            return key, text
    return "", ""


# ---- embedded-lyric comparison helpers ----

def strip_lrc_timestamps(line: str) -> str:
    line = re.sub(r"^\s*(?:\[[0-9]{1,2}:[0-9]{1,2}(?:\.[0-9]{1,3})?])+", "", line)
    line = re.sub(r"<[0-9]{1,2}:[0-9]{1,2}(?:\.[0-9]{1,3})?>", "", line)
    return line


def strip_yrc_markup(line: str) -> str:
    line = re.sub(r"^\s*\[[0-9]+,[0-9]+]", "", line)
    line = re.sub(r"\([0-9]+,[0-9]+(?:,[0-9]+)?\)", "", line)
    return line


def extract_lyric_line_text(line: str) -> str:
    line = line.strip()
    if not line:
        return ""

    if line.startswith("{") and line.endswith("}"):
        try:
            obj = json.loads(line)
            chunks = obj.get("c")
            if isinstance(chunks, list):
                return "".join(
                    str(c.get("tx") or "") for c in chunks if isinstance(c, dict)
                ).strip()
        except json.JSONDecodeError:
            pass

    if re.match(r"^\[[a-zA-Z]+:", line):
        return ""

    line = strip_lrc_timestamps(line)
    line = strip_yrc_markup(line)
    line = re.sub(r"\[[^]]*]", "", line)
    return line.strip()


def compact_lyric_text(raw: str) -> str:
    lines: list[str] = []
    for raw_line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        text = extract_lyric_line_text(raw_line)
        if not text:
            continue
        normalized = normalize_text(text)
        if not normalized:
            continue
        if any(normalized.startswith(normalize_text(prefix)) for prefix in CREDIT_PREFIXES):
            continue
        if ("演唱" in text or "歌手" in text) and len(text) <= 40:
            continue
        lines.append(text)

    joined = "\n".join(lines)
    joined = unicodedata.normalize("NFKC", joined).lower()
    joined = re.sub(r"[^\w぀-ヿ㐀-鿿가-힯]+", "", joined)
    return joined


def compare_lyrics(embedded_raw: str, netease_raw: str) -> dict[str, Any]:
    embedded = compact_lyric_text(embedded_raw)
    netease = compact_lyric_text(netease_raw)
    if not embedded and not netease:
        ratio_value = 1.0
        verdict = "empty_both"
    elif not embedded or not netease:
        ratio_value = 0.0
        verdict = "poor"
    else:
        ratio_value = max(
            SequenceMatcher(None, embedded, netease).ratio(),
            ngram_dice(embedded, netease, 4),
        )

        if ratio_value >= 0.82:
            verdict = "good"
        elif ratio_value >= 0.62:
            verdict = "review"
        else:
            verdict = "poor"

    return {
        "verdict": verdict,
        "similarity": round(ratio_value, 4),
        "embedded_chars": len(embedded),
        "netease_chars": len(netease),
        "embedded_preview": embedded[:120],
        "netease_preview": netease[:120],
    }


def ngram_dice(left: str, right: str, n: int) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    if len(left) < n or len(right) < n:
        return SequenceMatcher(None, left, right).ratio()
    left_counts = Counter(left[i : i + n] for i in range(len(left) - n + 1))
    right_counts = Counter(right[i : i + n] for i in range(len(right) - n + 1))
    overlap = sum(min(count, right_counts.get(token, 0)) for token, count in left_counts.items())
    total = sum(left_counts.values()) + sum(right_counts.values())
    return (2 * overlap / total) if total else 0.0


def compare_embedded(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Compare embedded lyrics with the matched provider payload.

    Reads lrc/yrc via main_lyric_text. QQ payloads (which carry _qrc_xml, not
    lrc/yrc) return no_netease_lyric here — QQ comparison is a stage-2 concern.
    """
    entries = read_audio_lyric_texts(path)
    embedded = pick_main_embedded_lyrics(entries)
    source, netease_text = main_lyric_text(payload)
    result: dict[str, Any] = {
        "embedded_count": len(entries),
        "embedded_lang": embedded.get("lang", "") if embedded else "",
        "embedded_tag": embedded.get("tag", "") if embedded else "",
        "netease_source": source,
    }
    if not embedded:
        result["verdict"] = "no_embedded"
        return result
    if not netease_text:
        result["verdict"] = "no_netease_lyric"
        return result
    result.update(compare_lyrics(embedded["text"], netease_text))
    return result


# ---- scan / mirror / planning ----

def mirror_relative_path(path: Path, root: Path) -> Path:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        return resolved_path.relative_to(resolved_root)
    except ValueError:
        return Path(path.name)


def planned_lyrics_paths(
    path: Path, library_root: Path, lyrics_root: Path, ttml_source: str = "netease",
    lyric_source_suffix: str = "netease",
) -> dict[str, str]:
    # ttml 旁车按音频路径镜像单层目录;同目录多文件按后缀区分来源——
    # 默认 <song>.ttml 是 apple 官方词(由 download_ttml.py/下载流程写),
    # <song>-{suffix}.ttml 是该来源增强词(网易 -netease / QQ -qq),与同目录的
    # apple 默认词并存(不覆盖)。raw json 存档只有网易有(QQ 不存 raw)。
    library_root_abs = library_root.resolve()
    lyrics_root_abs = lyrics_root.resolve()
    relative_audio = mirror_relative_path(path, library_root_abs)
    lyric_rel = relative_audio.with_suffix("")
    raw_key = f"{lyric_source_suffix}_raw_path"
    ttml_key = f"{lyric_source_suffix}_ttml_path"
    ttml_path = str(lyrics_root_abs / ttml_source / lyric_rel) + f"-{lyric_source_suffix}.ttml"
    # 防回归断言: 单层路径不应出现 <src>/<src> 重复段(旧翻盘脚本的 bug 模式)。
    _assert_no_doubled_source_segment(lyrics_root_abs, ttml_source, lyric_rel)
    return {
        "library_root": str(library_root_abs),
        "lyrics_root": str(lyrics_root_abs),
        "relative_audio_path": str(relative_audio),
        "am_ttml_path": str((lyrics_root_abs / "apple" / lyric_rel).with_suffix(".ttml")),
        raw_key: str((lyrics_root_abs / lyric_source_suffix / lyric_rel).with_suffix(".json")),
        ttml_key: ttml_path,
    }


def _assert_no_doubled_source_segment(
    lyrics_root_abs: Path, ttml_source: str, lyric_rel: Path,
) -> None:
    rel = Path(ttml_source) / lyric_rel
    parts = [p for p in rel.parts if p not in ("", ".", "/")]
    if not parts:
        return
    first = parts[0].lower()
    # lyric_rel 若本身以 source 段开头(如 library_root=Y:\music 时 mirror 含 common),
    # 拼 ttml_source=common 会产生 common/common/... 双层。
    for seg in parts[1:]:
        if seg.lower() == first:
            raise ValueError(
                f"planned netease ttml path has doubled source segment "
                f"'{first}/{first}' under lyricsRoot={lyrics_root_abs}, "
                f"ttml_source={ttml_source}, lyric_rel={lyric_rel}. "
                f"Set library-root to the audio source dir (e.g. Y:\\music\\common) "
                f"so the mirror path does not repeat the source segment."
            )


# NetEase (and QQ, symmetrically) return a "[00:00.00]暂无歌词" placeholder
# for songs tracked in their DB but lacking real lyrics. The lrc field is
# NON-EMPTY (it carries the timestamp line), so the naive "field present"
# check below would treat it as having lyrics. Strip timestamps first; if the
# remainder is just the placeholder phrase, there is no real lyric text.
_LRC_TIMESTAMP_RE = re.compile(r"\[\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?\]")
# NetEase placeholder phrases for "tracked but lyric-less" songs. Matched as
# substrings after timestamp stripping: these phrases are a few chars each, so
# a real lyric line (usually long) never contains them. Variants seen in the
# wild: "暂无歌词", "纯音乐", "纯音乐，请欣赏", "此歌曲为纯音乐，请您欣赏".
_PLACEHOLDER_PHRASES = ("暂无歌词", "纯音乐", "此歌曲为纯音乐，请您欣赏")


def _lyric_text_is_placeholder(text: str) -> bool:
    """True if a lyric field's text is NetEase's 暂无歌词/纯音乐 placeholder."""
    if not text:
        return False
    stripped = _LRC_TIMESTAMP_RE.sub("", text).strip()
    if not stripped:
        return False
    # A placeholder line is essentially JUST the phrase (a real lyric that
    # merely mentions 纯音乐 is long and has other content). Require the
    # phrase present AND the whole line ≤ a few chars beyond the phrase —
    # matching NetEase's single-line "暂无歌词"/"纯音乐，请欣赏" placeholders.
    return any(
        ph in stripped and len(stripped) <= len(ph) + 6
        for ph in _PLACEHOLDER_PHRASES
    )


def lyric_payload_has_text(payload: dict[str, Any]) -> bool:
    return any(
        _has_real_lyric_text(payload.get(name))
        for name in ("yrc", "lrc", "tlyric", "romalrc", "klyric")
    )


def _has_real_lyric_text(field: object) -> bool:
    """A lyric field is 'real text' if it's non-empty AND not a placeholder.

    NetEase lyric fields come back as a dict like {"lyric": "...", "code": 200}
    (or sometimes a bare string). The "[00:00.00]暂无歌词" placeholder has a
    non-empty .lyric, so a presence check alone would wrongly say has_text.
    """
    if field is None:
        return False
    text = field.get("lyric") if isinstance(field, dict) else field
    text = str(text or "").strip()
    if not text:
        return False
    if _lyric_text_is_placeholder(text):
        return False
    return True


def save_raw_payload(
    lyric_payload: dict[str, Any] | None,
    planned_paths: dict[str, str] | None,
    lyric_source_suffix: str,
    overwrite: bool,
) -> dict[str, Any]:
    """Write the raw lyric payload to its archive path.

    NetEase: raw JSON archive under <suffix>/<stem>.json. QQ has no raw archive
    (decrypted QRC XML is not worth a separate file) — returns skipped.
    """
    if lyric_source_suffix != "netease":
        # QQ (and future sources) skip raw archiving for now.
        if lyric_payload is None:
            return {"status": "skipped", "reason": "no_payload"}
        return {"status": "skipped", "reason": f"{lyric_source_suffix}_raw_not_supported"}
    if lyric_payload is None:
        return {"status": "skipped", "reason": "no_payload"}
    if not lyric_payload_has_text(lyric_payload):
        return {"status": "skipped", "reason": "no_lyric_text"}
    if not planned_paths:
        return {"status": "skipped", "reason": "no_planned_path"}

    target = Path(planned_paths[f"{lyric_source_suffix}_raw_path"])
    if target.exists() and not overwrite:
        return {"status": "exists", "path": str(target)}

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(lyric_payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp_path.replace(target)
    return {"status": "saved", "path": str(target)}


def save_ttml(
    lyric_payload: dict[str, Any] | None,
    planned_paths: dict[str, str] | None,
    lyric_source_suffix: str,
    overwrite: bool,
) -> dict[str, Any]:
    # 把原始歌词负载转成 TTML 并写到 <suffix>_ttml_path。
    # 网易用 payload_to_ttml(JSON→TTML, XML 转义对齐 Go)。
    # QQ 按 payload["_provider_source"] 走 qrc_xml_to_ttml。
    # 转换异常不崩批, 记录为 skipped。
    if lyric_payload is None:
        return {"status": "skipped", "reason": "no_payload"}
    if not lyric_payload_has_text(lyric_payload) and lyric_source_suffix == "netease":
        return {"status": "skipped", "reason": "no_lyric_text"}
    if not planned_paths:
        return {"status": "skipped", "reason": "no_planned_path"}

    target = Path(planned_paths[f"{lyric_source_suffix}_ttml_path"])
    if target.exists() and not overwrite:
        return {"status": "exists", "path": str(target)}

    try:
        if lyric_source_suffix == "qq":
            # QQ payload carries _qrc_xml; convert via qrc_xml_to_ttml.
            from backend.lyrics.lyric_match.converters import qrc_xml_to_ttml

            ttml = qrc_xml_to_ttml(lyric_payload.get("_qrc_xml", ""), "qq")
        else:
            ttml = payload_to_ttml(lyric_payload, lyric_source_suffix)
    except Exception as e:
        return {"status": "skipped", "reason": f"convert_error: {type(e).__name__}: {e}"}

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(ttml)
    tmp_path.replace(target)
    return {"status": "saved", "path": str(target)}


# Backward-compat aliases for any call site still using the old names.
def save_netease_payload(
    lyric_payload: dict[str, Any] | None,
    planned_paths: dict[str, str] | None,
    overwrite: bool,
) -> dict[str, Any]:
    return save_raw_payload(lyric_payload, planned_paths, "netease", overwrite)


def save_netease_ttml(
    lyric_payload: dict[str, Any] | None,
    planned_paths: dict[str, str] | None,
    overwrite: bool,
) -> dict[str, Any]:
    return save_ttml(lyric_payload, planned_paths, "netease", overwrite)
