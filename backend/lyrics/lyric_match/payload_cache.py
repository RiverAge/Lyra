"""在线匹配 raw payload 磁盘缓存（进程级单例）。

Lyra 的在线歌词匹配每次点「在线匹配」都完整重跑 8-17 次外部 API 往返
（NetEase weapi + QQ QRC + 强制 sleep），单次 8-20s。瓶颈在网络，converter
是微秒级。同一首歌重复匹配、候选切回再选、preview 拉词都重复请求。

本模块在 provider.fetch_lyrics 层做跨请求 raw payload 缓存：

- **键** = provider.source + ":" + str(candidate.id)
  provider song id 在 provider 侧永久稳定（网易/QQ 的歌曲 id），是唯一可信
  的跨请求缓存键。track_id (SQLite rowid) 同一首歌不同 rip 格式不命中，
  query 关键词归一化易撞车，都不如 provider song id 稳。
- **值** = provider.fetch_lyrics 返回的 raw dict（JSON-serializable）。
  缓存 raw 而非最终 TTML——converter 是纯 CPU 微秒级，重跑无负担；且 raw
  是最稳的缓存值（converter 输出随 source 参数变体，key 管理复杂）。
- **TTL** = 7 天。provider 侧数据会更新（网易改词、QQ 补注音），缓存不能永久。
  TTL 靠文件 mtime，过期不主动删（下次 set 时 replace 覆盖）。
- **介质** = 磁盘 JSON 文件，目录挨着 db（<db_dir>/lyric_cache/）。零新配置、
  自动跟随 db 位置、重启不丢、易手动清理（删目录即可）。

**缓存语义尊重各 provider 自己的判断**（关键，决定缓存值能否原样存回）：
- 成功 payload / placeholder marker（QQ `_qrc_status:placeholder/no_content`）
  → 缓存（QQ 自己 qq.py 也缓存这些 marker，省重复探测）
- 解密错误（QQ `_qrc_status:decrypt_error`）→ **绝不缓存**（对齐 qq.py:303
  注释「Don't cache decrypt errors — allow a retry」），允许后续重试命中真实数据

注入点在 provider 层（fetch_lyrics_cached helper + QQ fetch_lyrics 内部），
覆盖 runner / preview / find_qrc_candidate 三处调 fetch_lyrics 的路径。
scoring/decision 不动——纯在 fetch_lyrics 层，零决策回归。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# TTL：7 天。provider 侧数据会更新（网易改词、QQ 补注音），缓存不能永久。
_TTL = timedelta(days=7)

# 同 key 并发回源防击穿。单 worker 下 fetch_lyrics 是 await，两次同 candidate
# 的并发请求可能同时 miss → 都回源。Lock 让第二个等第一个写完再读缓存。
_LOCK = asyncio.Lock()


class PayloadCache:
    """磁盘 raw payload 缓存。键 = (source, candidate_id)，值 = JSON dict。

    进程级单例（get_payload_cache），不挂 provider 实例——provider 每次请求
    新建实例（lyrics_match_routes._build_providers），实例缓存随请求销毁。
    """

    def __init__(self, root: Path, ttl: timedelta = _TTL) -> None:
        self._root = root
        self._ttl = ttl
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str, candidate_id: int) -> Path:
        # source 已规整成 netease/qq（_build_providers 白名单），candidate_id 是
        # int。文件名安全，无需额外 sanitize。
        return self._root / f"{source}_{int(candidate_id)}.json"

    async def get(self, source: str, candidate_id: int) -> dict[str, Any] | None:
        """命中返回 payload dict，miss/过期/损坏返回 None（回源，不崩）。"""
        p = self._path(source, candidate_id)
        try:
            if not p.is_file():
                return None
            # TTL 靠 mtime
            age = datetime.now().timestamp() - p.stat().st_mtime
            if age > self._ttl.total_seconds():
                return None  # 过期：不主动删，下次 set 时 replace 覆盖
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("payload cache read failed: %s", p, exc_info=True)
            return None  # 缓存损坏 = 回源，不让匹配崩

    async def set(self, source: str, candidate_id: int, payload: dict[str, Any] | None) -> None:
        """写 payload。None 跳过；QQ decrypt_error 跳过（允许重试）。"""
        if payload is None:
            return
        # QQ 语义：decrypt_error 绝不缓存（对齐 qq.py:303 注释），允许后续重试。
        # 其他 provider 无 _qrc_status 字段，startswith("") 不会误判。
        status = str(payload.get("_qrc_status", "") or "")
        if status.startswith("decrypt_error"):
            return
        async with _LOCK:
            p = self._path(source, candidate_id)
            # 原子写：tmp + replace，避免并发读到半截 JSON
            tmp = p.with_suffix(".json.tmp")
            try:
                tmp.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp.replace(p)
            except Exception:
                logger.warning("payload cache write failed: %s", p, exc_info=True)
                # 残留 tmp 不影响读（读只认 .json）
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# 模块级单例工厂
# ---------------------------------------------------------------------------

_INSTANCE: PayloadCache | None = None


def get_payload_cache() -> PayloadCache:
    """进程级单例。lazy 建目录——第一次用时按 db 位置定缓存目录。

    目录 = <db_path 的目录>/lyric_cache/。零新配置，自动跟随 db 位置，
    重启不丢。跟 log_dir 是平行的「Lyra 数据落点」概念，不污染用户音乐库
    （sidecar 在 <music_library>/.lyrics/ 是用户数据，缓存是 Lyra 内部数据）。
    """
    global _INSTANCE
    if _INSTANCE is None:
        from backend.config import get_settings

        db = get_settings().db_path_resolved()
        _INSTANCE = PayloadCache(db.parent / "lyric_cache")
    return _INSTANCE


def reset_payload_cache_for_test(root: Path | None) -> None:
    """测试用：重置单例到指定目录（None = 清掉单例，下次 get 重建到真实 db 旁）。"""
    global _INSTANCE
    if root is None:
        _INSTANCE = None
    else:
        _INSTANCE = PayloadCache(Path(root))
