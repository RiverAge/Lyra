"""Lyra 索引存储层。

提供 SQLite schema 初始化与查询能力。
每个操作独立获取连接（aiosqlite.connect），单 worker 无需连接池。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL（基线从零初始化，含所有索引/约束/默认值）
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT    NOT NULL DEFAULT '',
    artist       TEXT    NOT NULL DEFAULT '',
    album_artist TEXT    NOT NULL DEFAULT '',
    album        TEXT    NOT NULL DEFAULT '',
    path         TEXT    NOT NULL UNIQUE,
    track        INTEGER,
    disc         INTEGER,
    year         INTEGER,
    duration     INTEGER NOT NULL DEFAULT 0,
    bitrate      INTEGER,
    codec        TEXT,
    samplerate   INTEGER,
    tag_map      TEXT    NOT NULL DEFAULT '{}',
    mtime        INTEGER NOT NULL DEFAULT 0,
    size         INTEGER NOT NULL DEFAULT 0,
    has_cover    INTEGER NOT NULL DEFAULT 0,
    folder_hash  TEXT,
    created_at   INTEGER NOT NULL DEFAULT 0,
    updated_at   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tracks_title  ON tracks(title);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album  ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_tracks_path   ON tracks(path);

-- scanner_status: 扫描进度与状态真源（§3.6 状态落库，SSE 断线重连可恢复）
CREATE TABLE IF NOT EXISTS scanner_status (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    state           TEXT    NOT NULL DEFAULT 'idle',
    scan_type       TEXT,
    count           INTEGER NOT NULL DEFAULT 0,
    folder_count    INTEGER NOT NULL DEFAULT 0,
    started_at      INTEGER,
    last_scanned_at INTEGER,
    error_message   TEXT
);

-- folder_watermarks: folder 级 hash watermark，判定是否需要重扫
CREATE TABLE IF NOT EXISTS folder_watermarks (
    folder_path TEXT    NOT NULL PRIMARY KEY,
    folder_hash TEXT    NOT NULL,
    updated_at  INTEGER NOT NULL DEFAULT 0
);
"""


# ---------------------------------------------------------------------------
# IndexStore
# ---------------------------------------------------------------------------


class IndexStore:
    """SQLite 索引存储。

    每个操作异步打开/关闭连接，确保并发安全。
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = str(db_path)

    # ---- schema ----

    async def init_schema(self) -> None:
        """初始化数据库 schema（幂等：已存在则跳过）。

        使用 CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS。
        所有索引/约束直接体现在 DDL 中（审计规则 §3.3）。
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            await db.executescript(_SCHEMA_SQL)
            await db.commit()
        logger.info("Schema initialized (db=%s)", self._db_path)

    # ---- track queries ----

    async def count_tracks(self) -> int:
        """返回 tracks 表总行数。"""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute("SELECT COUNT(*) AS cnt FROM tracks")
            row = await cursor.fetchone()
            return int(row["cnt"]) if row else 0

    async def list_tracks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """分页查询 tracks。

        Args:
            limit: 返回条数上限。
            offset: 偏移量。

        Returns:
            sqlite3.Row 列表，按 id 升序。
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT * FROM tracks ORDER BY id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return list(rows)

    async def get_track_by_path(self, path: str) -> sqlite3.Row | None:
        """按 path 查询单条 track。

        Returns:
            sqlite3.Row 或 None（不存在时）。
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT * FROM tracks WHERE path = ?",
                (path,),
            )
            return await cursor.fetchone()

    async def get_all_paths(self) -> list[str]:
        """获取所有已索引的路径（删除检测用）。"""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute("SELECT path FROM tracks")
            rows = await cursor.fetchall()
            return [row["path"] for row in rows]

    # ---- track write ----

    async def insert_track(self, **fields: object) -> int:
        """插入一条 track 记录。

        Args:
            **fields: 列名 = 值的键值对。缺少的列使用 DEFAULT。

        Returns:
            新行的 rowid（整数）。
        """
        columns = list(fields.keys())
        placeholders = ", ".join("?" for _ in columns)
        values = list(fields.values())

        sql = f"INSERT INTO tracks ({', '.join(columns)}) VALUES ({placeholders})"

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(sql, values)
            await db.commit()
            rowid = cursor.lastrowid
            assert rowid is not None, "INSERT did not return a rowid"
            return rowid

    async def upsert_track(self, **fields: object) -> int:
        """插入或更新一条 track 记录（ON CONFLICT(path) DO UPDATE）。

        若 path 已存在，更新所有提供的列并设置 updated_at；
        若 path 不存在，插入新行（created_at + updated_at 若未提供则用当前时间）。

        Args:
            **fields: 列名 = 值的键值对。

        Returns:
            受影响行的 rowid。
        """
        columns = list(fields.keys())
        placeholders = ", ".join("?" for _ in columns)
        values = list(fields.values())

        # 构造 SET 子句：excluded.<col> 引用 INSERT 中提供的值
        # 注意：path 是冲突列，不更新自身
        set_clauses = []
        for col in columns:
            if col == "path":
                continue
            set_clauses.append(f"{col} = excluded.{col}")

        # 如果没提供 updated_at，显式设为当前时间（确保每次 upsert 都更新时间戳）
        if "updated_at" not in columns:
            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            columns.append("updated_at")
            placeholders += ", ?"
            values.append(now_ms)
            set_clauses.append("updated_at = excluded.updated_at")

        sql = (
            f"INSERT INTO tracks ({', '.join(columns)}) VALUES ({placeholders})"
            f" ON CONFLICT(path) DO UPDATE SET {', '.join(set_clauses)}"
        )

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(sql, values)
            await db.commit()
            rowid = cursor.lastrowid
            assert rowid is not None, "UPSERT did not return a rowid"
            return rowid

    async def delete_track_by_path(self, path: str) -> None:
        """按 path 删除一条 track 记录。"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM tracks WHERE path = ?", (path,))
            await db.commit()

    # ---- scanner_status ----

    async def get_scanner_status(self) -> sqlite3.Row | None:
        """读取 scanner_status 单行。

        Returns:
            sqlite3.Row 或 None（表为空时——首次启动尚未写入）。
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute("SELECT * FROM scanner_status WHERE id = 1")
            return await cursor.fetchone()

    async def set_scanner_status(self, **fields: object) -> None:
        """写入/更新 scanner_status 单行（upsert on id=1）。

        Args:
            **fields: 要更新的列（state, scan_type, count, folder_count,
                      started_at, last_scanned_at, error_message）。
                     仅更新提供的列，其余保持原值。
        """
        # 先确保单行存在
        await self._ensure_scanner_status_row()

        set_parts = []
        values: list[object] = []
        for col, val in fields.items():
            set_parts.append(f"{col} = ?")
            values.append(val)

        if not set_parts:
            return

        sql = f"UPDATE scanner_status SET {', '.join(set_parts)} WHERE id = 1"

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(sql, values)
            await db.commit()

    async def _ensure_scanner_status_row(self) -> None:
        """确保 scanner_status 表有 id=1 的行（INSERT OR IGNORE）。"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO scanner_status (id, state, count, folder_count) "
                "VALUES (1, 'idle', 0, 0)"
            )
            await db.commit()

    # ---- folder_watermarks ----

    async def get_folder_hash(self, folder_path: str) -> str | None:
        """读取 folder 的 hash watermark。

        Returns:
            folder_hash 字符串，或 None（未记录过）。
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT folder_hash FROM folder_watermarks WHERE folder_path = ?",
                (folder_path,),
            )
            row = await cursor.fetchone()
            return row["folder_hash"] if row else None

    async def set_folder_hash(self, folder_path: str, folder_hash: str) -> None:
        """写入/更新 folder 的 hash watermark。"""
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT INTO folder_watermarks (folder_path, folder_hash, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(folder_path) DO UPDATE SET "
                "folder_hash = excluded.folder_hash, updated_at = excluded.updated_at",
                (folder_path, folder_hash, now_ms),
            )
            await db.commit()


# ---------------------------------------------------------------------------
# 模块级单例（startup 注入，endpoint 读取）
# ---------------------------------------------------------------------------

_store: IndexStore | None = None


def set_store(store: IndexStore | None) -> None:
    """设置或清除全局 IndexStore 实例。"""
    global _store
    _store = store


def get_store() -> IndexStore | None:
    """获取全局 IndexStore 实例。"""
    return _store