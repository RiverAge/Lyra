"""Lyra 索引存储层。

提供 SQLite schema 初始化与查询能力。
每个操作独立获取连接（aiosqlite.connect），单 worker 无需连接池。
"""

from __future__ import annotations

import logging
import sqlite3
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

    # ---- query ----

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

    # ---- write（测试用；A2 scanner 写入入口） ----

    async def insert_track(self, **fields: object) -> int:
        """插入一条 track 记录。

        Args:
            **fields: 列名 = 值的键值对。缺少的列使用 DEFAULT。

        Returns:
            新行的 rowid（整数）。
        """
        # 构造 INSERT 语句——仅插入显式提供的列
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