"""Lyra 索引扫描器。

walk + mutagen 读标签 → store.upsert_track()。
folder 级 hash watermark + 文件级 mtime 二次过滤。
所有 mutagen 调用通过 asyncio.run_in_executor 执行（同步库不阻塞事件循环）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from backend.index.store import IndexStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 支持的音频文件扩展名（§3.3 lyrics_io DEFAULT_EXTENSIONS）
DEFAULT_EXTENSIONS: tuple[str, ...] = (".m4a", ".mp4", ".m4p", ".flac", ".mp3")

# 忽略的目录/文件名（§3.5）
_IGNORED_DIR_NAMES: frozenset[str] = frozenset(
    {"$RECYCLE.BIN", "#snapshot", ".git", "__MACOSX"}
)


# ---------------------------------------------------------------------------
# 同步辅助函数（供 run_in_executor 调用）
# ---------------------------------------------------------------------------


def _should_ignore(path: Path) -> bool:
    """判断文件/目录是否应被忽略。

    检查路径的所有组成部分：任何一级是 dot 开头或属于忽略列表则跳过。
    """
    # 检查路径的每个部分
    for part in path.parts:
        if _should_ignore_path_part(part):
            return True
    return False


def _should_ignore_path_part(name: str) -> bool:
    """判断单个路径组成部分是否应被忽略（用在 os.walk dirnames 就地过滤）。"""
    if name.startswith("."):
        return True
    if name in _IGNORED_DIR_NAMES:
        return True
    return False


def _normalize_tag_values(raw_values: list[object]) -> list[str]:
    """将 mutagen tag 值列表转为字符串列表。

    处理 bytes（UTF-8 解码）、MP4FreeForm、及其他标量类型。
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


def _is_audio_file(path: Path) -> bool:
    """判断是否为支持的音频文件。"""
    return path.suffix.lower() in DEFAULT_EXTENSIONS


def _compute_folder_hash(folder_path: Path) -> str:
    """计算 folder 级 hash watermark。

    MD5 of (子文件 name + size + mtime 三元组)，非内容哈希。
    只考虑该目录直属子文件（非递归），且仅音频文件。
    """
    entries: list[tuple[str, int, int]] = []
    try:
        for entry in sorted(folder_path.iterdir(), key=lambda e: e.name):
            if not entry.is_file():
                continue
            if _should_ignore(entry):
                continue
            if not _is_audio_file(entry):
                continue
            stat = entry.stat()
            entries.append((entry.name, stat.st_size, int(stat.st_mtime * 1000)))
    except OSError:
        pass

    raw = json.dumps(entries, sort_keys=True).encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def _read_audio_tags(file_path: Path) -> dict[str, object] | None:
    """用 mutagen 读音频标签（同步，在 executor 中运行）。

    Returns:
        dict 含 title/artist/album_artist/album/track/disc/year/
        duration/bitrate/codec/samplerate/tag_map/has_cover/mtime/size/path，
        或 None（文件无法读取/损坏）。
    """
    import mutagen
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4

    path_str = str(file_path)

    try:
        mf = mutagen.File(path_str)
    except Exception:
        logger.debug("mutagen 无法打开文件: %s", path_str, exc_info=True)
        return None

    if mf is None:
        logger.debug("mutagen 不支持的格式: %s", path_str)
        return None

    tags: dict[str, object] = {}

    # ---- 时长 & 比特率 & 采样率 ----
    if hasattr(mf, "info") and mf.info is not None:
        tags["duration"] = int(getattr(mf.info, "length", 0) * 1000)
        br = getattr(mf.info, "bitrate", None)
        tags["bitrate"] = int(br) if br is not None else None
        sr = getattr(mf.info, "sample_rate", None)
        tags["samplerate"] = int(sr) if sr is not None else None
    else:
        tags["duration"] = 0

    # ---- 编解码器 ----
    if isinstance(mf, MP4):
        tags["codec"] = "alac"
    elif isinstance(mf, FLAC):
        tags["codec"] = "flac"
    elif isinstance(mf, MP3):
        tags["codec"] = "mp3"
    else:
        tags["codec"] = None

    # ---- 原始 tag map ----
    raw_tags: dict[str, list[str]] = {}

    if isinstance(mf, MP4):
        for key in mf:
            raw_values = mf[key]
            # 健壮处理标量值（cpil bool / tmpo int / pgap int 等）——
            # mutagen 对非列表 tag 直接存标量，for 循环迭代会抛 TypeError
            if not isinstance(raw_values, list):
                raw_values = [raw_values]
            raw_tags[key] = _normalize_tag_values(raw_values)
    elif isinstance(mf, FLAC):
        for key in mf:
            raw_tags[key] = [str(v) for v in mf[key]]
    elif isinstance(mf, MP3):
        for key in mf:
            values = mf[key]
            try:
                # 大多数 ID3 帧都是 list[Frame]，也有单个 Frame 的情况
                items = values if isinstance(values, list) else [values]
                raw_strs: list[str] = []
                for item in items:
                    # 优先取 .text（TIT2/TPE1/TALB 等标准文本帧）
                    text = getattr(item, "text", None)
                    if text is not None:
                        if isinstance(text, list):
                            raw_strs.extend(str(t) for t in text)
                        else:
                            raw_strs.append(str(text))
                    else:
                        raw_strs.append(str(item))
                raw_tags[key] = raw_strs
            except Exception:
                raw_tags[key] = [str(values)]

    # ---- 提取常用字段 ----
    def _first(values: object) -> str:
        if values and isinstance(values, list) and len(values) > 0:
            return str(values[0])
        return ""

    if isinstance(mf, MP4):
        tags["title"] = _first(mf.get("©nam"))
        tags["artist"] = _first(mf.get("©ART"))
        tags["album_artist"] = _first(mf.get("aART"))
        tags["album"] = _first(mf.get("©alb"))
        trkn = mf.get("trkn")
        tags["track"] = trkn[0][0] if trkn and trkn[0] else None
        disk = mf.get("disk")
        tags["disc"] = disk[0][0] if disk and disk[0] else None
        day_raw = mf.get("©day")
        if day_raw:
            try:
                tags["year"] = int(str(day_raw[0])[:4])
            except (ValueError, IndexError):
                tags["year"] = None
        tags["has_cover"] = 1 if "covr" in mf else 0
    elif isinstance(mf, FLAC):
        tags["title"] = _first(mf.get("title"))
        tags["artist"] = _first(mf.get("artist"))
        tags["album_artist"] = _first(mf.get("albumartist"))
        tags["album"] = _first(mf.get("album"))
        trkn = mf.get("tracknumber")
        tags["track"] = int(str(trkn[0]).split("/")[0]) if trkn else None
        disc = mf.get("discnumber")
        tags["disc"] = int(str(disc[0]).split("/")[0]) if disc else None
        date_raw = mf.get("date")
        if date_raw:
            try:
                tags["year"] = int(str(date_raw[0])[:4])
            except (ValueError, IndexError):
                tags["year"] = None
        tags["has_cover"] = 1 if mf.pictures else 0
    elif isinstance(mf, MP3):
        tags["title"] = _first(mf.get("TIT2"))
        tags["artist"] = _first(mf.get("TPE1"))
        tags["album_artist"] = _first(mf.get("TPE2"))
        tags["album"] = _first(mf.get("TALB"))
        trkn = mf.get("TRCK")
        tags["track"] = int(str(trkn).split("/")[0]) if trkn else None
        disc_raw = mf.get("TPOS")
        tags["disc"] = int(str(disc_raw).split("/")[0]) if disc_raw else None
        date_raw = mf.get("TDRC")
        if date_raw:
            try:
                tags["year"] = int(str(date_raw)[:4])
            except (ValueError, IndexError):
                tags["year"] = None
        tags["has_cover"] = 1 if any(k.startswith("APIC:") for k in mf) else 0

    tags["tag_map"] = json.dumps(raw_tags, ensure_ascii=False)

    # ---- 文件系统字段 ----
    try:
        stat = file_path.stat()
        tags["mtime"] = int(stat.st_mtime * 1000)
        tags["size"] = stat.st_size
    except OSError:
        tags["mtime"] = 0
        tags["size"] = 0

    tags["path"] = str(file_path).replace("\\", "/")

    return tags


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class Scanner:
    """索引扫描器。

    负责：定点扫描单个目录 + 全量扫描 + 删除检测。
    运行时更新 scanner_status 表作为进度真源。
    """

    def __init__(self, store: IndexStore, library_root: Path) -> None:
        self._store = store
        self._library_root = library_root.resolve()
        self._on_progress: Callable[[int, int, int], Awaitable[object]] | None = None

    def set_on_progress(
        self, callback: Callable[[int, int, int], Awaitable[object]]
    ) -> None:
        """设置进度回调 async callback(cumulative_files, cumulative_folders, total_files)。"""
        self._on_progress = callback

    # ---- 扫描入口 ----

    async def scan_folder(self, folder_path: Path) -> int:
        """定点扫描单个目录。

        1. 计算 folder hash → 与 watermark 比 → 不变则跳过
        2. 遍历目录内音频文件，mtime 二次过滤
        3. mutagen 读 tag → store.upsert_track()
        4. 更新 folder watermark

        Args:
            folder_path: 要扫描的目录（绝对路径）。

        Returns:
            本次扫描处理的文件数。
        """
        folder_path = folder_path.resolve()

        if not folder_path.is_dir():
            logger.debug("目录不存在，跳过扫描: %s", folder_path)
            return 0

        if _should_ignore(folder_path):
            return 0

        loop = asyncio.get_running_loop()
        current_hash = await loop.run_in_executor(None, _compute_folder_hash, folder_path)

        folder_path_str = str(folder_path).replace("\\", "/")
        stored_hash = await self._store.get_folder_hash(folder_path_str)

        if stored_hash is not None and stored_hash == current_hash:
            logger.debug("folder hash 未变，跳过: %s", folder_path_str)
            return 0

        # 遍历目录内音频文件
        try:
            entries = sorted(folder_path.iterdir(), key=lambda e: e.name)
        except OSError:
            logger.warning("无法读取目录: %s", folder_path_str)
            return 0

        processed = 0
        now_ms = int(datetime.now(UTC).timestamp() * 1000)

        for entry in entries:
            if not entry.is_file():
                continue
            if _should_ignore(entry):
                continue
            if not _is_audio_file(entry):
                continue

            entry_path_str = str(entry).replace("\\", "/")

            # mtime 二次过滤
            file_mtime_ms = int(entry.stat().st_mtime * 1000)
            existing = await self._store.get_track_by_path(entry_path_str)
            if existing is not None:
                db_mtime = existing["mtime"]
                if file_mtime_ms <= db_mtime:
                    logger.debug("mtime 未变，跳过: %s", entry_path_str)
                    processed += 1
                    continue

            # 读标签 + 写库
            tags = await loop.run_in_executor(None, _read_audio_tags, entry)
            if tags is None:
                logger.debug("无法读取标签，跳过: %s", entry_path_str)
                processed += 1
                continue

            if "created_at" not in tags:
                tags["created_at"] = now_ms
            tags["updated_at"] = now_ms

            try:
                await self._store.upsert_track(**tags)
            except Exception:
                logger.exception("写入 track 失败: %s", entry_path_str)
                processed += 1
                continue

            processed += 1

        # 更新 watermark
        await self._store.set_folder_hash(folder_path_str, current_hash)

        return processed

    async def scan_all(self) -> dict[str, int]:
        """全量扫描入口。

        递归遍历音乐库根下整棵目录树，对每个含音频文件的叶子目录
        逐个 scan_folder。完成后做删除检测。
        进度通过 on_progress 回调 + scanner_status 表推送。

        folder_count 口径：本次全量扫描中实际调用了 scan_folder 的目录数
        （即含音频文件且未被 hash 跳过的叶子目录数）。

        total_files 口径：os.walk 阶段统计的所有匹配扩展名文件总数。
        count 口径：已处理的文件数。folder hash 跳过的目录中文件也计入 count
        （跳过=无需处理也算"已处理"，确保扫描完成时 count == total_files）。

        Returns:
            {"files_processed": N, "files_deleted": D, "folders_processed": F,
             "total_files": T}
        """
        now_ms = int(datetime.now(UTC).timestamp() * 1000)

        await self._store.set_scanner_status(
            state="scanning",
            scan_type="full",
            count=0,
            folder_count=0,
            total_files=0,
            started_at=now_ms,
            error_message=None,
        )

        total_files = 0
        total_folders = 0
        last_error: str | None = None

        try:
            # 递归收集所有含音频文件的叶子目录，同时统计文件总数
            candidate_dirs: list[Path] = []
            dir_file_counts: dict[str, int] = {}  # dir_path → 文件数
            for dirpath_str, dirnames, filenames in os.walk(self._library_root):
                dirpath = Path(dirpath_str)

                # 忽略规则：从 dirnames 就地移除要跳过的目录（os.walk 不会进入它们）
                dirnames[:] = [
                    d for d in dirnames if not _should_ignore_path_part(d)
                ]

                # 忽略当前目录自身（如根下 .hidden 目录会被 dirnames 过滤，但
                # 若根自身含 dot 前缀，也需要跳过）
                if _should_ignore(dirpath):
                    continue

                # 统计该目录内匹配扩展名的文件数（与 _compute_folder_hash 口径一致：
                # 只算直属音频文件，忽略 .dot 文件）
                audio_count = 0
                for fname in filenames:
                    if _should_ignore_path_part(fname):
                        continue
                    if Path(fname).suffix.lower() in DEFAULT_EXTENSIONS:
                        audio_count += 1

                if audio_count > 0:
                    candidate_dirs.append(dirpath)
                    dir_key = str(dirpath).replace("\\", "/")
                    dir_file_counts[dir_key] = audio_count
                    total_files += audio_count

            # 按路径排序，确保扫描顺序确定
            candidate_dirs.sort(key=lambda p: str(p))

            # 写入 total_files（os.walk 阶段统计完毕，后续不再变）
            await self._store.set_scanner_status(total_files=total_files)

            processed_files = 0

            for folder in candidate_dirs:
                try:
                    files_done = await self.scan_folder(folder)
                    folder_key = str(folder).replace("\\", "/")

                    # folder hash 跳过时 scan_folder 返回 0，
                    # 但这些文件仍算"已处理"（跳过=无需处理），
                    # 将该目录的文件数计入 processed 以确保进度完整
                    if files_done == 0:
                        processed_files += dir_file_counts.get(folder_key, 0)
                    else:
                        processed_files += files_done
                    total_folders += 1

                    # 更新 scanner_status 累计
                    await self._store.set_scanner_status(
                        count=processed_files,
                        folder_count=total_folders,
                    )

                    # 进度回调（累计）
                    if self._on_progress is not None:
                        await self._on_progress(processed_files, total_folders, total_files)

                except Exception:
                    logger.exception("扫描目录失败: %s", folder)
                    last_error = f"扫描目录失败: {folder}"

            # 删除检测
            deleted = await self._detect_deletions()

            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            await self._store.set_scanner_status(
                state="idle",
                scan_type=None,
                count=processed_files,
                last_scanned_at=now_ms,
                error_message=last_error,
            )

            logger.info(
                "全量扫描完成: files=%d, deleted=%d, folders=%d, total=%d",
                processed_files, deleted, total_folders, total_files,
            )

            return {
                "files_processed": processed_files,
                "files_deleted": deleted,
                "folders_processed": total_folders,
                "total_files": total_files,
            }

        except Exception:
            logger.exception("全量扫描异常中断")
            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            await self._store.set_scanner_status(
                state="error",
                last_scanned_at=now_ms,
                error_message=str(last_error or "扫描异常中断"),
            )
            raise

    async def _detect_deletions(self) -> int:
        """删除检测：库有但文件系统没有的记录 → 删除。"""
        db_paths = await self._store.get_all_paths()
        deleted = 0

        for db_path_str in db_paths:
            file_path = Path(db_path_str)
            if not file_path.exists():
                await self._store.delete_track_by_path(db_path_str)
                deleted += 1
                logger.info("删除检测: 文件已不存在，从索引移除: %s", db_path_str)

        return deleted


# ---------------------------------------------------------------------------
# 模块级单例（startup 注入）
# ---------------------------------------------------------------------------

_scanner: Scanner | None = None


def set_scanner(scanner: Scanner | None) -> None:
    """设置或清除全局 Scanner 实例。"""
    global _scanner
    _scanner = scanner


def get_scanner() -> Scanner | None:
    """获取全局 Scanner 实例。"""
    return _scanner