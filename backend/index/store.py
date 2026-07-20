"""Lyra 索引存储层。

提供 SQLite schema 初始化与查询能力。
每个操作独立获取连接（aiosqlite.connect），单 worker 无需连接池。
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 列表查询字段：列表端点（/api/library）只返回展示必需列。
# tracks 表已无 tag_map 列（B 方案：元数据现读文件 via /meta/{id}/tags），
# 详情端点 /library/{id} 也不再返回 tag_map。
# 同时排除 mtime/folder_hash/created_at/updated_at（内部字段，前端不用）。
_TRACK_LIST_COLUMNS = (
    "id, title, artist, album_artist, album, path, track, disc, year, "
    "duration, bitrate, codec, samplerate, size, has_cover"
)

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
-- total_files: os.walk 阶段统计的匹配扩展名文件总数（含 hash 跳过的目录中的文件）
-- count: 已处理的文件数（含 hash 跳过的，跳过=无需处理也算"已处理"）
CREATE TABLE IF NOT EXISTS scanner_status (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    state           TEXT    NOT NULL DEFAULT 'idle',
    scan_type       TEXT,
    count           INTEGER NOT NULL DEFAULT 0,
    folder_count    INTEGER NOT NULL DEFAULT 0,
    total_files     INTEGER NOT NULL DEFAULT 0,
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

-- app_settings: Web UI 可配置的运行期设置（单行表，id=1）
-- 加列时改 DDL（CREATE TABLE IF NOT EXISTS 对已存在表不重建，需 ALTER 或迁移）
CREATE TABLE IF NOT EXISTS app_settings (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    credits_base_url TEXT    NOT NULL DEFAULT '',  -- 空=直连 music.apple.com
    updated_at       INTEGER NOT NULL DEFAULT 0
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

    @asynccontextmanager
    async def _connect(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """打开连接 + 设 busy_timeout，统一所有 DB 访问入口。

        WAL 下读不阻塞写、写不阻塞读，但**写写仍互斥**——多连接同时写
        （scan_all 逐文件 upsert + watcher 增量 upsert）抢写锁时，默认
        ``busy_timeout=0`` 会立刻抛 ``database is locked`` 而非等待重试。
        设 5s busy_timeout 让抢锁的连接等待对方释放而非直接报错。
        同时每连接设 row_factory（与原 `async with aiosqlite.connect` 一致）。
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            await db.execute("PRAGMA busy_timeout=5000")
            yield db

    # ---- schema ----

    async def init_schema(self) -> None:
        """初始化数据库 schema（幂等：已存在则跳过）。

        使用 CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS。
        所有索引/约束直接体现在 DDL 中（审计规则 §3.3）。
        对已存在表补列用 ALTER TABLE（幂等：检测列存在性后 ALTER）。
        """
        async with self._connect() as db:
            # WAL：写不阻塞读、commit 不强制 fsync，扫描期 22966 次 upsert
            # 吞吐显著提升（FULL→NORMAL；WAL 下 synchronous=NORMAL 仍安全，
            # 最多丢最后一个未 checkpoint 的事务，Lyra 索引数据可重建）。
            # journal_mode 是 DB 持久属性，写一次即可；这里幂等重设无害。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA synchronous=NORMAL")
            await db.executescript(_SCHEMA_SQL)
            # 增量迁移：补列（CREATE TABLE IF NOT EXISTS 对已存在表不重建）
            await self._migrate_scanner_status_total_files(db)
            await db.commit()
        logger.info("Schema initialized (db=%s)", self._db_path)

    async def _migrate_scanner_status_total_files(self, db: aiosqlite.Connection) -> None:
        """scanner_status 表加 total_files 列（幂等：列已存在则跳过）。

        旧库（无 total_files 列）启动时自动迁移，不丢数据。
        """
        # PRAGMA table_info 返回列信息，检查 total_files 是否已存在
        cursor = await db.execute("PRAGMA table_info(scanner_status)")
        columns = await cursor.fetchall()
        column_names = {row[1] for row in columns}  # row[1] = column name

        if "total_files" not in column_names:
            await db.execute(
                "ALTER TABLE scanner_status ADD COLUMN total_files INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Migrated scanner_status: added total_files column")

    # ---- track queries ----

    async def count_tracks(self) -> int:
        """返回 tracks 表总行数。"""
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute("SELECT COUNT(*) AS cnt FROM tracks")
            row = await cursor.fetchone()
            return int(row["cnt"]) if row else 0

    # ---- 聚合统计 ----

    async def library_stats(self) -> dict[str, int | float]:
        """曲库聚合统计（供首页统计卡）。

        Returns:
            {track_count, album_count, total_duration_sec, lossless_ratio}
            - lossless_ratio: 0.0~1.0（无损曲目数 / 曲目总数，空库为 0.0）
        """
        # 无损 codec 白名单（大小写不敏感：入库逻辑存小写，如 alac/flac）
        lossless_codecs = ("ALAC", "FLAC", "WAV", "APE", "DSD")
        placeholders = ",".join("?" for _ in lossless_codecs)

        import time
        t0 = time.monotonic()
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                f"""
                SELECT
                    COUNT(*) AS track_count,
                    COUNT(DISTINCT album) FILTER (WHERE album != '') AS album_count,
                    COALESCE(SUM(duration), 0) / 1000 AS total_duration_sec,
                    COUNT(*) FILTER (WHERE UPPER(codec) IN ({placeholders})) AS lossless_count
                FROM tracks
                """,
                lossless_codecs,
            )
            row = await cursor.fetchone()
            logger.info("[stats] aggregate query db_ms=%.0f", (time.monotonic() - t0) * 1000)
            if not row:
                return {
                    "track_count": 0,
                    "album_count": 0,
                    "total_duration_sec": 0,
                    "lossless_ratio": 0.0,
                }
            track_count = int(row["track_count"])
            lossless_count = int(row["lossless_count"])
            return {
                "track_count": track_count,
                "album_count": int(row["album_count"]),
                "total_duration_sec": int(row["total_duration_sec"]),
                "lossless_ratio": round(lossless_count / track_count, 4) if track_count else 0.0,
            }

    @staticmethod
    def _build_track_filters(
        *,
        artist: str | None,
        album: str | None,
        codec: str | None,
    ) -> tuple[str, list[object]]:
        """构造 tracks 过滤 WHERE 子句（参数化）。

        文本字段（artist/album）用 LIKE 模糊匹配，codec 精确匹配。
        返回 (where_sql, params)；无过滤时 where_sql 为空串。
        """
        clauses: list[str] = []
        params: list[object] = []
        if artist:
            clauses.append("artist LIKE ?")
            params.append(f"%{artist}%")
        if album:
            clauses.append("album LIKE ?")
            params.append(f"%{album}%")
        if codec:
            clauses.append("UPPER(codec) = UPPER(?)")
            params.append(codec)
        if not clauses:
            return "", []
        where_sql = "WHERE " + " AND ".join(clauses)
        return where_sql, params

    async def count_tracks_filtered(
        self,
        *,
        artist: str | None = None,
        album: str | None = None,
        codec: str | None = None,
    ) -> int:
        """按过滤条件 count tracks（供分页 total）。无过滤等价于 count_tracks。"""
        where_sql, params = self._build_track_filters(
            artist=artist, album=album, codec=codec
        )
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                f"SELECT COUNT(*) AS cnt FROM tracks {where_sql}",
                params,
            )
            row = await cursor.fetchone()
            return int(row["cnt"]) if row else 0

    async def list_tracks_filtered(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        artist: str | None = None,
        album: str | None = None,
        codec: str | None = None,
    ) -> list[sqlite3.Row]:
        """按过滤条件分页查询 tracks。无过滤等价于 list_tracks。

        Returns:
            sqlite3.Row 列表，按 id 降序（最近添加在前）。
        """
        where_sql, params = self._build_track_filters(
            artist=artist, album=album, codec=codec
        )
        params = [*params, limit, offset]
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                f"SELECT {_TRACK_LIST_COLUMNS} FROM tracks {where_sql} "
                "ORDER BY id DESC LIMIT ? OFFSET ?",
                params,
            )
            rows = await cursor.fetchall()
            return list(rows)

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
            sqlite3.Row 列表，按 id 降序（最近添加在前）。
        """
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                f"SELECT {_TRACK_LIST_COLUMNS} FROM tracks ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cursor.fetchall()
            return list(rows)

    async def search_tracks(self, q: str, *, limit: int = 10) -> list[sqlite3.Row]:
        """跨 title/artist/album 模糊搜索（全局 ⌘K 搜索框用）。

        单个关键词同时匹配三个字段（OR LIKE），命中任一即返回。
        用 LIKE '%q%'（非前缀索引扫描）——2 万行全表扫约几十 ms，
        搜索框只取前 N 条，可接受。若日后曲库涨到十万级再考虑 FTS5。

        Args:
            q: 搜索关键词（已 trim；空串返回 []，不查 DB）。
            limit: 返回条数上限，默认 10（搜索框下拉只需几条）。

        Returns:
            sqlite3.Row 列表（列表列集），按 id 升序。
        """
        import time

        q = q.strip()
        if not q:
            return []
        pattern = f"%{q}%"
        t0 = time.monotonic()
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                f"SELECT {_TRACK_LIST_COLUMNS} FROM tracks "
                "WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? "
                "ORDER BY id ASC LIMIT ?",
                (pattern, pattern, pattern, limit),
            )
            rows = await cursor.fetchall()
            elapsed_ms = (time.monotonic() - t0) * 1000
            logger.info(
                "[search] q=%r limit=%d hits=%d db_ms=%.1f",
                q,
                limit,
                len(rows),
                elapsed_ms,
            )
            return list(rows)

    async def get_track_by_path(self, path: str) -> sqlite3.Row | None:
        """按 path 查询单条 track。

        Returns:
            sqlite3.Row 或 None（不存在时）。
        """
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT * FROM tracks WHERE path = ?",
                (path,),
            )
            return await cursor.fetchone()

    async def get_track_by_id(self, rowid: int) -> sqlite3.Row | None:
        """按 rowid 查询单条 track。

        Args:
            rowid: 行 ID（自增主键）。

        Returns:
            sqlite3.Row 或 None（不存在时）。
        """
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(
                "SELECT * FROM tracks WHERE id = ?",
                (rowid,),
            )
            return await cursor.fetchone()

    async def get_all_paths(self) -> list[str]:
        """获取所有已索引的路径（删除检测用）。"""
        async with self._connect() as db:
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

        async with self._connect() as db:
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

        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute(sql, values)
            await db.commit()
            rowid = cursor.lastrowid
            assert rowid is not None, "UPSERT did not return a rowid"
            return rowid

    # 批量 upsert 的固定列集（与 _read_audio_tags 输出 + created_at/updated_at 对齐）。
    # 固定列而非每行动态列：批量 INSERT...VALUES 多行需要所有行列数一致，
    # 取并集会让 SQL 静态可预编译，executemany 一次提交一个事务。
    # 缺失的可空列（track/disc/year/bitrate/samplerate）填 None（列允许 NULL）；
    # NOT NULL DEFAULT 列由 scanner 保证提供（title/.../duration/size/has_cover）。
    _BATCH_COLUMNS = (
        "title", "artist", "album_artist", "album", "path",
        "track", "disc", "year", "duration", "bitrate", "codec", "samplerate",
        "mtime", "size", "has_cover", "created_at", "updated_at",
    )

    async def upsert_tracks_batch(self, rows: list[dict]) -> int:
        """批量 upsert 多条 track（单事务 executemany）。

        相比逐条 upsert_track（每条开连接+commit），batch 把一个 folder 的所有
        文件（通常 10-30 行）合到一个事务里提交：连接开关 1 次、commit 1 次、
        写锁持有时间从"逐文件几乎全程独占"降到"folder 级短占"——扫描期读端点
        （list/stats）能穿插进来，不再被写压垮超时。

        列集固定（_BATCH_COLUMNS），每行映射到该列集；缺失可空列填 None。
        path 冲突走 ON CONFLICT DO UPDATE 更新其余列。created_at/updated_at
        由调用方（scanner）填好，本方法不动时间戳逻辑。

        Args:
            rows: track dict 列表（键为列名，可含 _BATCH_COLUMNS 子集；
                  缺失列按可空性填 None）。

        Returns:
            受影响行数（executemany rowcount，-1 表示某些驱动不返回）。
        """
        if not rows:
            return 0

        cols = self._BATCH_COLUMNS
        placeholders = "(" + ", ".join("?" for _ in cols) + ")"
        # path 是冲突列，SET 排除 path
        set_cols = [c for c in cols if c != "path"]
        set_clause = ", ".join(f"{c} = excluded.{c}" for c in set_cols)
        sql = (
            f"INSERT INTO tracks ({', '.join(cols)}) VALUES {placeholders}"
            f" ON CONFLICT(path) DO UPDATE SET {set_clause}"
        )

        # 映射每行到固定列顺序（缺失填 None）
        batch_values = [
            [row.get(c) for c in cols] for row in rows
        ]

        async with self._connect() as db:
            await db.executemany(sql, batch_values)
            await db.commit()
            return db.total_changes or len(rows)

    async def delete_track_by_path(self, path: str) -> None:
        """按 path 删除一条 track 记录。"""
        async with self._connect() as db:
            await db.execute("DELETE FROM tracks WHERE path = ?", (path,))
            await db.commit()

    # ---- scanner_status ----

    async def get_scanner_status(self) -> sqlite3.Row | None:
        """读取 scanner_status 单行。

        Returns:
            sqlite3.Row 或 None（表为空时——首次启动尚未写入）。
        """
        async with self._connect() as db:
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

        async with self._connect() as db:
            await db.execute(sql, values)
            await db.commit()

    async def _ensure_scanner_status_row(self) -> None:
        """确保 scanner_status 表有 id=1 的行（INSERT OR IGNORE）。"""
        async with self._connect() as db:
            await db.execute(
                "INSERT OR IGNORE INTO scanner_status "
                "(id, state, count, folder_count, total_files) "
                "VALUES (1, 'idle', 0, 0, 0)"
            )
            await db.commit()

    async def clear_orphan_scanning_state(self) -> None:
        """启动时清理孤儿 scanning 状态。

        进程被强杀（SIGKILL/OOM）时 scan_all 末尾的 state=idle 没执行，
        scanner_status 会卡在 scanning。进程刚启动 = 不可能在扫，强制置回
        idle，否则 scanner_routes 的手动触发会因 state==scanning 返回 409
        被挡住。自动续扫（_initial_scan）不走该检查不受影响，但孤儿态
        期间手动按钮失效——这里填掉这个真实小坑。

        记 error_message 便于排查（正常停止不会有这条）。
        """
        await self._ensure_scanner_status_row()
        async with self._connect() as db:
            await db.execute(
                "UPDATE scanner_status "
                "SET state = 'idle', "
                "    scan_type = NULL, "
                "    error_message = 'recovered from orphan scanning state' "
                "WHERE id = 1 AND state = 'scanning'"
            )
            await db.commit()

    # ---- folder_watermarks ----

    async def get_folder_hash(self, folder_path: str) -> str | None:
        """读取 folder 的 hash watermark。

        Returns:
            folder_hash 字符串，或 None（未记录过）。
        """
        async with self._connect() as db:
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
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO folder_watermarks (folder_path, folder_hash, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(folder_path) DO UPDATE SET "
                "folder_hash = excluded.folder_hash, updated_at = excluded.updated_at",
                (folder_path, folder_hash, now_ms),
            )
            await db.commit()

    # ---- app_settings ----

    async def get_app_settings(self) -> sqlite3.Row | None:
        """读取 app_settings 单行。

        Returns:
            sqlite3.Row 或 None（首次启动尚未写入时——调用方应回退默认值）。
        """
        async with self._connect() as db:
            db.row_factory = sqlite3.Row
            cursor = await db.execute("SELECT * FROM app_settings WHERE id = 1")
            return await cursor.fetchone()

    async def set_app_settings(self, **fields: object) -> None:
        """写入/更新 app_settings 单行（upsert on id=1）。

        仅更新提供的列，其余保持原值。自动刷新 updated_at。
        """
        await self._ensure_app_settings_row()

        set_parts: list[str] = []
        values: list[object] = []
        for col, val in fields.items():
            set_parts.append(f"{col} = ?")
            values.append(val)

        # 自动更新 updated_at
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        set_parts.append("updated_at = ?")
        values.append(now_ms)

        sql = f"UPDATE app_settings SET {', '.join(set_parts)} WHERE id = 1"

        async with self._connect() as db:
            await db.execute(sql, values)
            await db.commit()

    async def _ensure_app_settings_row(self) -> None:
        """确保 app_settings 表有 id=1 的行（INSERT OR IGNORE）。"""
        async with self._connect() as db:
            await db.execute(
                "INSERT OR IGNORE INTO app_settings (id) VALUES (1)"
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