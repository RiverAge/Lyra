"""Lyra 元数据写入模块。

对磁盘文件就地写标签，支持 MP4/FLAC/MP3 三格式。
也提供读取 tag_map 的能力（供 meta_routes 写后回读验证）。

字段映射表（FIELD_MAP）是本模块与 diff.py 的共享数据契约——
diff.py 从此导入映射以确保互逆一致。
语义字段名 → mutagen 原生 key 的映射关系，三方格式各列其一。
"""

from __future__ import annotations

import logging
from pathlib import Path

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TALB, TCOM, TCON, TIT2, TPE1, TPE2, TPUB, TXXX
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 字段映射表（权威来源）
# 语义字段名 → (MP4 atom key, FLAC vorbis key, MP3 ID3v2 frame key)
# None 表示该格式不支持此字段
# ---------------------------------------------------------------------------
# 【注意】diff.py 从此导入 FIELD_MAP + 反向映射表，确保两处映射互逆一致

FIELD_MAP: dict[str, tuple[str | None, str | None, str | None]] = {
    "title":         ("©nam",                            "title",        "TIT2"),
    "artist":        ("©ART",                            "artist",       "TPE1"),
    "album_artist":  ("aART",                            "albumartist",  "TPE2"),
    "album":         ("©alb",                            "album",        "TALB"),
    "composer":      ("©wrt",                            "composer",     "TCOM"),
    "lyricist":      ("----:com.apple.iTunes:lyricist",  "lyricist",     "TXXX:LYRICIST"),
    "producer":      ("----:com.apple.iTunes:producer",  "producer",     "TXXX:PRODUCER"),
    "mixer":         ("----:com.apple.iTunes:mixer",     "mixer",        "TXXX:MIXER"),
    "engineer":      ("----:com.apple.iTunes:engineer",  "engineer",     "TXXX:ENGINEER"),
    "remixer":       ("----:com.apple.iTunes:remixer",   "remixer",      "TXXX:REMIXER"),
    "arranger":      ("----:com.apple.iTunes:arranger",  "arranger",     "TXXX:ARRANGER"),
    "conductor":     ("----:com.apple.iTunes:conductor", "conductor",    "TXXX:CONDUCTOR"),
    "djmixer":       ("----:com.apple.iTunes:djmixer",   "djmixer",      "TXXX:DJMIXER"),
    "performer":     ("----:com.apple.iTunes:performer", "performer",    "TXXX:PERFORMER"),
    "genre":         ("©gen",                            "genre",        "TCON"),
    "copyright":     ("cprt",                            "copyright",    None),
    "record_company":("©pub",                            "organization", "TPUB"),
    "isrc":          ("----:com.apple.iTunes:ISRC",      "isrc",         None),
    "barcode":       ("----:com.apple.iTunes:BARCODE",   "barcode",      None),
}

# ---------------------------------------------------------------------------
# 反向映射（mutagen key → 语义字段名）
# diff.py 用它们将本地 tag_map（raw mutagen key）对齐到语义口径
# ---------------------------------------------------------------------------

MP4_KEY_TO_SEMANTIC: dict[str, str] = {}
FLAC_KEY_TO_SEMANTIC: dict[str, str] = {}
MP3_KEY_TO_SEMANTIC: dict[str, str] = {}

_for_sem: str
_for_mp4: str | None
_for_flac: str | None
_for_mp3: str | None
for _for_sem, (_for_mp4, _for_flac, _for_mp3) in FIELD_MAP.items():
    if _for_mp4 is not None:
        MP4_KEY_TO_SEMANTIC[_for_mp4] = _for_sem
    if _for_flac is not None:
        FLAC_KEY_TO_SEMANTIC[_for_flac] = _for_sem
    if _for_mp3 is not None:
        MP3_KEY_TO_SEMANTIC[_for_mp3] = _for_sem


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------


def write_metadata(
    file_path: Path,
    after_fields: dict[str, list[str]],
) -> dict[str, object]:
    """对磁盘文件就地写入元数据标签。

    自动根据文件格式（MP4/FLAC/MP3）分派到对应的写入器。
    写前先删除要写字段的旧值（大小写不敏感），防累积。

    Args:
        file_path: 音频文件绝对路径。
        after_fields: 语义字段名 → list[str] 的 dict。

    Returns:
        {"fields_written": int, "format": str}
        fields_written 是实际写入的字段数（仅计入格式支持的字段）。

    Raises:
        TypeError: 文件不是受支持的格式。
        ValueError: 文件无法打开或写入。
    """
    import mutagen

    mf = mutagen.File(str(file_path))
    if mf is None:
        raise ValueError(f"Cannot open file: {file_path}")

    if isinstance(mf, MP4):
        fmt = "alac"
        count = _write_mp4(file_path, after_fields)
    elif isinstance(mf, FLAC):
        fmt = "flac"
        count = _write_flac(file_path, after_fields)
    elif isinstance(mf, MP3):
        fmt = "mp3"
        count = _write_mp3(file_path, after_fields)
    else:
        raise TypeError(f"Unsupported format: {type(mf).__name__} ({file_path})")

    return {"fields_written": count, "format": fmt}


def read_tag_map(file_path: Path) -> tuple[dict[str, list[str]], str]:
    """读取文件的 tag_map + 推断格式。

    返回的 tag_map 格式与 scanner._read_audio_tags 的 raw_tags 一致：
    dict[str, list[str]]（mutagen 原生 key → 字符串值列表）。

    Returns:
        (tag_map, codec) where codec 为 "alac" | "flac" | "mp3"。

    Raises:
        ValueError: 文件无法打开或格式不受支持。
    """
    import mutagen

    mf = mutagen.File(str(file_path))
    if mf is None:
        raise ValueError(f"Cannot open file: {file_path}")

    tag_map: dict[str, list[str]] = {}

    if isinstance(mf, MP4):
        codec = "alac"
        for key in mf:
            raw_values = mf[key]
            if not isinstance(raw_values, list):
                raw_values = [raw_values]
            tag_map[key] = _normalize_tag_values(list(raw_values))
    elif isinstance(mf, FLAC):
        codec = "flac"
        for key in mf:
            tag_map[key] = [str(v) for v in mf[key]]
    elif isinstance(mf, MP3):
        codec = "mp3"
        for key in mf:
            values = mf[key]
            try:
                items = values if isinstance(values, list) else [values]
                strs: list[str] = []
                for item in items:
                    text = getattr(item, "text", None)
                    if text is not None:
                        if isinstance(text, list):
                            strs.extend(str(t) for t in text)
                        else:
                            strs.append(str(text))
                    else:
                        strs.append(str(item))
                tag_map[key] = strs
            except Exception:
                tag_map[key] = [str(values)]
    else:
        raise ValueError(f"Unsupported format: {type(mf).__name__} ({file_path})")

    return tag_map, codec


def get_supported_fields() -> dict[str, object]:
    """返回支持的字段清单（供前端展示字段映射关系）。

    Returns:
        {
            "fields": [
                {"semantic": "title", "mp4": "©nam", "flac": "title", "mp3": "TIT2"},
                ...
            ]
        }
    """
    field_list: list[dict[str, object]] = []
    for sem, (mp4_k, flac_k, mp3_k) in FIELD_MAP.items():
        field_list.append({
            "semantic": sem,
            "mp4": mp4_k,
            "flac": flac_k,
            "mp3": mp3_k,
        })
    return {"fields": field_list}


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

_TAG_VALUE_T = list[object]


def _normalize_tag_values(raw_values: _TAG_VALUE_T) -> list[str]:
    """将 tag value 列表转为字符串列表。

    处理 bytes（UTF-8 解码）、MP4FreeForm、及其他标量类型。
    与 scanner._normalize_tag_values 逻辑一致。
    """
    result: list[str] = []
    for v in raw_values:
        if isinstance(v, bytes):
            try:
                result.append(v.decode("utf-8", errors="replace"))
            except Exception:
                result.append(repr(v))
        else:
            result.append(str(v))
    return result


ITUNES_PREFIXES = ("----:com.apple.iTunes:", "----:com.apple.iTunes\x00:")


def _mp4_delete_freeform(mf: MP4, canonical_key: str) -> None:
    """从 MP4 文件中按大小写不敏感 + \\x00 变体删除 freeform key。

    canonical_key 形如 "----:com.apple.iTunes:lyricist"。
    匹配时忽略大小写以及 \\x00 分隔符变体。
    """
    # 提取 tag 名称部分（最后一个 colon 之后）
    target_suffix = canonical_key.rsplit(":", 1)[-1].lower()
    to_delete: list[str] = []
    for key in list(mf.keys()):
        if not key.startswith(ITUNES_PREFIXES):
            continue
        suffix = key.rsplit(":", 1)[-1].rstrip("\x00").lower()
        if suffix == target_suffix:
            to_delete.append(key)
    for key in to_delete:
        del mf[key]


def _mp3_delete_txxx(id3: ID3, desc: str) -> None:
    """按描述名大小写不敏感删除 TXXX 帧。"""
    desc_lower = desc.lower()
    to_delete: list[str] = []
    for key in list(id3.keys()):
        if key.startswith("TXXX:"):
            existing_desc = key[5:].lower()
            if existing_desc == desc_lower:
                to_delete.append(key)
    for key in to_delete:
        del id3[key]


# ---------------------------------------------------------------------------
# MP4 写入
# ---------------------------------------------------------------------------


def _write_mp4(file_path: Path, after_fields: dict[str, list[str]]) -> int:
    """写入 MP4 标签。"""
    mf = mutagen.File(str(file_path))
    if mf is None or not isinstance(mf, MP4):
        raise TypeError(f"Not an MP4 file: {file_path}")

    # -- 删除旧值 --
    for sem_name, values in after_fields.items():
        if not values:
            continue
        mp4_key = FIELD_MAP.get(sem_name, (None, None, None))[0]
        if mp4_key is None:
            continue

        if mp4_key.startswith("----:com.apple.iTunes:"):
            # freeform 大小写不敏感删除
            _mp4_delete_freeform(mf, mp4_key)
        elif mp4_key in mf:
            # 精确删除标准 atom / 特殊 atom
            del mf[mp4_key]

    # -- 写入新值 --
    written = 0
    for sem_name, values in after_fields.items():
        if not values:
            continue
        mp4_key = FIELD_MAP.get(sem_name, (None, None, None))[0]
        if mp4_key is None:
            continue

        if mp4_key in ("trkn", "disk"):
            # track/disc number tuple: values[0] = "N" or "N/T"
            first = values[0]
            if "/" in first:
                parts = first.split("/", 1)
                num, total = int(parts[0]), int(parts[1])
            else:
                num, total = int(first), 0
            mf[mp4_key] = [(num, total)]
        elif mp4_key == "covr":
            # 封面：本里程碑不写封面，静默跳过
            continue
        elif mp4_key == "cpil":
            # compilation boolean
            mf[mp4_key] = values[0].lower() in ("1", "true", "yes")
        elif mp4_key.startswith("----:com.apple.iTunes:"):
            # freeform — 值需 encode 为 bytes
            mf[mp4_key] = [v.encode("utf-8") for v in values]
        else:
            # 标准 atom（©nam, ©ART, ©wrt 等）
            mf[mp4_key] = values

        written += 1

    mf.save()
    return written


# ---------------------------------------------------------------------------
# FLAC 写入
# ---------------------------------------------------------------------------


def _write_flac(file_path: Path, after_fields: dict[str, list[str]]) -> int:
    """写入 FLAC 标签（vorbis comment）。"""
    mf = mutagen.File(str(file_path))
    if mf is None or not isinstance(mf, FLAC):
        raise TypeError(f"Not a FLAC file: {file_path}")

    written = 0
    for sem_name, values in after_fields.items():
        if not values:
            continue
        flac_key = FIELD_MAP.get(sem_name, (None, None, None))[1]
        if flac_key is None:
            continue

        # 删除旧值：FLAC 的 vorbis key 大小写不敏感，用小写匹配删除
        flac_key_lower = flac_key.lower()
        to_delete = [k for k in mf if k.lower() == flac_key_lower]
        for k in to_delete:
            del mf[k]

        # 写入新值
        mf[flac_key] = values
        written += 1

    mf.save()
    return written


# ---------------------------------------------------------------------------
# MP3 写入
# ---------------------------------------------------------------------------


def _write_mp3(file_path: Path, after_fields: dict[str, list[str]]) -> int:
    """写入 MP3 ID3v2 标签。

    标准文本帧（TIT2/TPE1/TPE2/TALB/TCOM/TCON/TPUB）用帧类；
    自定义字段用 TXXX 帧，描述名取自 FIELD_MAP 中的 mp3_key。
    """
    try:
        id3 = ID3(str(file_path))
    except Exception:
        # 无 ID3 标签时创建一个新标签
        id3 = ID3()

    written = 0
    for sem_name, values in after_fields.items():
        if not values:
            continue
        mp3_key = FIELD_MAP.get(sem_name, (None, None, None))[2]
        if mp3_key is None:
            continue

        # -- 删除旧值 --
        if mp3_key.startswith("TXXX:"):
            desc = mp3_key[5:]
            _mp3_delete_txxx(id3, desc)
        else:
            id3.delall(mp3_key)

        # -- 写入新值 --
        if mp3_key == "TIT2":
            id3.add(TIT2(encoding=3, text=values))
        elif mp3_key == "TPE1":
            id3.add(TPE1(encoding=3, text=values))
        elif mp3_key == "TPE2":
            id3.add(TPE2(encoding=3, text=values))
        elif mp3_key == "TALB":
            id3.add(TALB(encoding=3, text=values))
        elif mp3_key == "TCOM":
            id3.add(TCOM(encoding=3, text=values))
        elif mp3_key == "TCON":
            id3.add(TCON(encoding=3, text=values))
        elif mp3_key == "TPUB":
            id3.add(TPUB(encoding=3, text=values))
        else:
            # TXXX 自定义帧
            desc = mp3_key[5:] if mp3_key.startswith("TXXX:") else mp3_key
            id3.add(TXXX(encoding=3, desc=desc, text=values))

        written += 1

    id3.save(str(file_path), v2_version=3)
    return written