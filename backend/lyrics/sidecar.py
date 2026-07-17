"""Lyra 歌词 sidecar 读写层。

负责 `.lyrics/` 目录下 TTML/JSON 文件的路径计算与 CRUD。
路径算法照搬 AGENTS.md §3.3 + 参考源 `lyrics_io.py`（mirror_relative_path /
planned_lyrics_paths / _assert_no_doubled_source_segment），签名一致——
这是有意为之的副本：M5-A 也在搬同一组纯函数，合流时由 architect 收敛。

路径约定（AGENTS.md §3.3）::

    音频      : <library_root>/apple/Artist/Album/01 Song.m4a
    apple 词 : <library_root>/.lyrics/apple/Artist/Album/01 Song.ttml
    网易增强 : <library_root>/.lyrics/apple/Artist/Album/01 Song-netease.ttml
    网易 raw : <library_root>/.lyrics/apple/Artist/Album/01 Song.json
    QQ 增强  : <library_root>/.lyrics/apple/Artist/Album/01 Song-qq.ttml

规则：
- 所有来源 sidecar **平铺在 ``.lyrics/apple/`` 下**（音频镜像目录，保留
  ``apple/`` 首段），靠文件名后缀区分。这是对齐 navidrome lyric-bridge
  的扫描契约——bridge 只在该一个目录扫后缀文件。
- ``<song>.ttml`` 是 apple 官方词（无后缀）；``<song>-{suffix}.ttml`` 是来源
  增强词（``-netease`` / ``-qq``），与 apple 默认词并存（不覆盖）。
- raw json 存档只有网易有（QQ 不存 raw），与同 source 的 TTML 同目录。
- source 不进目录段，只进文件名后缀（apple 除外）。

路径安全是审计重点：所有 sidecar 路径必须落在 ``library_root/.lyrics/`` 下，
防 ``../`` 越出。用 resolve() + is_relative_to()，与 apple_routes 同模式。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

# sidecar 根目录名（固定，不可配——AGENTS.md §3.3 约定）。
LYRICS_DIR_NAME = ".lyrics"

# 支持的来源（apple=官方词，netease/qq=增强词）。
Source = Literal["apple", "netease", "qq"]
# 增强词来源（apple 没有 -后缀，是默认 <song>.ttml）。
ENHANCED_SOURCES: tuple[Source, ...] = ("netease", "qq")


# ---------------------------------------------------------------------------
# 路径计算（从参考源 lyrics_io.py 搬运的纯函数副本，签名一致）
# ---------------------------------------------------------------------------


def mirror_relative_path(path: Path, root: Path) -> Path:
    """音频 path 相对 library_root 的镜像相对路径。

    无法 relative_to 时（path 不在 root 下）退化为文件名，
    与参考源一致——上层路径安全校验会拦截非法 path。
    """
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    try:
        return resolved_path.relative_to(resolved_root)
    except ValueError:
        return Path(path.name)


def planned_lyrics_paths(
    path: Path,
    library_root: Path,
    lyrics_root: Path,
    ttml_source: str = "netease",
    lyric_source_suffix: str = "netease",
) -> dict[str, str]:
    """计算音频 path 对应的所有 sidecar 落盘路径。

    照搬参考源 lyrics_io.py:planned_lyrics_paths，签名一致。

    Args:
        path: 音频文件路径。
        library_root: 音乐库根（音频所在）。
        lyrics_root: sidecar 根（通常 ``library_root/.lyrics``）。
        ttml_source: TTML 旁车目录名（来源）。
        lyric_source_suffix: 增强词文件名后缀（``-<suffix>.ttml``）。

    Returns:
        含 library_root/lyrics_root/relative_audio_path/am_ttml_path/
        ``{suffix}_raw_path``/``{suffix}_ttml_path`` 的 dict。
    """
    library_root_abs = library_root.resolve()
    lyrics_root_abs = lyrics_root.resolve()
    relative_audio = mirror_relative_path(path, library_root_abs)
    lyric_rel = relative_audio.with_suffix("")
    raw_key = f"{lyric_source_suffix}_raw_path"
    ttml_key = f"{lyric_source_suffix}_ttml_path"
    ttml_path = str(lyrics_root_abs / ttml_source / lyric_rel) + f"-{lyric_source_suffix}.ttml"
    # 防回归断言: 单层路径不应出现 <src>/<src> 重复段（旧翻盘脚本的 bug 模式）。
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
    """防回归：lyric_rel 不应导致 ``<src>/<src>`` 重复段。

    照搬参考源 lyrics_io.py:_assert_no_doubled_source_segment。
    """
    rel = Path(ttml_source) / lyric_rel
    parts = [p for p in rel.parts if p not in ("", ".", "/")]
    if not parts:
        return
    first = parts[0].lower()
    # lyric_rel 若本身以 source 段开头（如 library_root=Y:\music 时 mirror 含 common），
    # 拼 ttml_source=common 会产生 common/common/... 双层。
    for seg in parts[1:]:
        if seg.lower() == first:
            raise ValueError(
                f"planned netease ttml path has doubled source segment "
                f"'{first}/{first}' under lyricsRoot={lyrics_root_abs}, "
                f"ttml_source={ttml_source}, lyric_rel={lyric_rel}. "
                f"Set --library-root to the audio source dir (e.g. Y:\\music\\common) "
                f"so the mirror path does not repeat the source segment."
            )


# ---------------------------------------------------------------------------
# sidecar 路径查询（Lyra 侧封装）
#
# 注意：planned_lyrics_paths（上方死代码副本）把 <source>/ 段前置到完整
# mirror 前，会保留音频 apple/ 段（前置语义，双写 apple/apple）。Lyra 实际
# 落盘用 sidecar_path_for 的**平铺语义**（对齐 lyric-bridge）：所有来源平铺
# 在 .lyrics/apple/ 下，source 只进文件名后缀。两者语义不同——sidecar_path_for
# 不走 planned_lyrics_paths。planned_lyrics_paths 作为纯函数副本保留，当前
# 死代码（Web 路由不调，CLI run_batch 已按 §3.5 丢弃），供未来合流收敛。
# ---------------------------------------------------------------------------


def lyrics_root_for(library_root: Path) -> Path:
    """返回 library_root 对应的 sidecar 根（``<library_root>/.lyrics``）。"""
    return library_root.resolve() / LYRICS_DIR_NAME


def _sidecar_relative(track_path: Path, library_root: Path) -> Path:
    """sidecar 相对路径体：音频完整 mirror 去扩展名（含 apple/ 首段）。

    对齐 navidrome lyric-bridge 的扫描目录：bridge 在
    ``lyricsRoot + 音频所在目录``（即 ``.lyrics/`` + 音频镜像路径的 Dir）
    里扫 ``<song>.ttml`` / ``<song>-netease.ttml`` / ``<song>-qq.ttml``。
    故 sidecar 体必须**完整保留音频镜像**（含 ``apple/`` 首段），source 只
    进文件名后缀，不进目录段。

    mirror 只剩文件名时（音频直接在 library_root 下，无 ``apple/`` 前缀）
    返回纯文件名（无目录）。
    """
    rel = mirror_relative_path(track_path, library_root)
    return rel.with_suffix("")


def sidecar_path_for(
    track_path: Path, library_root: Path, source: Source,
) -> Path:
    """计算指定来源的 sidecar 文件路径（所有来源平铺在 ``.lyrics/apple/`` 下）。

    对齐 navidrome lyric-bridge：bridge 只在 ``.lyrics/<音频镜像目录>`` 一个
    目录里扫 ``<song>.ttml``（apple）/``<song>-netease.ttml``/``<song>-qq.ttml``，
    故所有来源 sidecar 必须落在**同一目录**（音频镜像目录），靠文件名后缀区分。

    - apple → ``.lyrics/apple/<Artist/Album/song>.ttml``（无后缀，默认官方词）
    - netease → ``.lyrics/apple/<Artist/Album/song>-netease.ttml``（增强词）
    - qq → ``.lyrics/apple/<Artist/Album/song>-qq.ttml``（增强词，无 raw）

    音频镜像首段 ``apple/`` 保留（来自音频路径，非 source 段）。source 不进
    目录，只进文件名后缀（apple 除外）。增强词后缀 ``-<source>.ttml`` 是 bridge
    扫描契约，别改。
    """
    root = library_root.resolve()
    lyrics_root = lyrics_root_for(root)
    body = _sidecar_relative(track_path, root)
    # body 已含音频镜像首段（apple/），直接拼到 lyrics_root 下——所有来源
    # 平铺在 .lyrics/apple/ 下（对齐 lyric-bridge 扫描目录），不再额外加 source 段。
    base = (lyrics_root / body).with_suffix(".ttml")
    if source == "apple":
        return base  # <song>.ttml 无后缀
    # 增强词：<song>-<source>.ttml（先建 <song>.ttml 再 with_name 改名，
    # 避免 body.parent 在纯文件名场景退化成 "." 的边界问题）
    return base.with_name(f"{base.stem}-{source}.ttml")


def raw_json_path_for(
    track_path: Path, library_root: Path, source: Source,
) -> Path | None:
    """计算 raw json 存档路径（仅 netease 有，apple/qq 返回 None）。

    落在 ``.lyrics/apple/<Artist/Album/song>.json``（与同 source 的 TTML
    平铺在同一镜像目录，对齐 lyric-bridge 扫描路径）。
    """
    if source != "netease":
        return None
    root = library_root.resolve()
    lyrics_root = lyrics_root_for(root)
    body = _sidecar_relative(track_path, root)
    # body 已含 apple/ 首段，平铺在 .lyrics/apple/ 下（对齐 lyric-bridge 扫描路径）
    return (lyrics_root / body).with_suffix(".json")


def is_within_lyrics_root(sidecar_path: Path, library_root: Path) -> bool:
    """路径安全校验：sidecar_path 是否落在 ``<library_root>/.lyrics/`` 下。

    用 resolve() + is_relative_to()，与 apple_routes._resolve_track 同模式。
    防恶意 ``../`` 越出 sidecar 根。
    """
    lyrics_root = lyrics_root_for(library_root)
    try:
        resolved = sidecar_path.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved.is_relative_to(lyrics_root.resolve())


# ---------------------------------------------------------------------------
# TTML / JSON 文件 CRUD
# ---------------------------------------------------------------------------


def read_sidecar(path: Path) -> str | None:
    """读 TTML/JSON 文件内容。不存在返回 None。"""
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def write_sidecar(path: Path, content: str) -> None:
    """写 TTML/JSON 文件，含父目录 mkdir。原子写（tmp + replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def delete_sidecar(path: Path) -> bool:
    """删除 sidecar 文件。返回是否实际删除了（不存在返回 False）。"""
    if not path.is_file():
        return False
    path.unlink()
    return True


def list_sidecars(
    track_path: Path, library_root: Path,
) -> list[dict[str, object]]:
    """列出该 track 的所有 sidecar 文件 + 内容。

    遍历 apple/netease/qq 三来源 + netease raw json，
    返回存在的条目（路径 + source + format + content）。

    路径安全：每条路径都经 is_within_lyrics_root 校验，越界跳过。
    """
    result: list[dict[str, object]] = []
    for source in ("apple", "netease", "qq"):
        sidecar_path = sidecar_path_for(track_path, library_root, source)
        if not is_within_lyrics_root(sidecar_path, library_root):
            continue
        content = read_sidecar(sidecar_path)
        if content is not None:
            result.append({
                "source": source,
                "format": "ttml",
                "path": str(sidecar_path),
                "content": content,
            })
        # raw json 仅 netease 有
        raw_path = raw_json_path_for(track_path, library_root, source)
        if raw_path is not None and is_within_lyrics_root(raw_path, library_root):
            raw_content = read_sidecar(raw_path)
            if raw_content is not None:
                result.append({
                    "source": "netease",
                    "format": "json",
                    "path": str(raw_path),
                    "content": raw_content,
                })
    return result


def read_raw_json(path: Path) -> dict[str, object] | None:
    """读 raw json sidecar 并解析为 dict。不存在/解析失败返回 None。"""
    text = read_sidecar(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None
