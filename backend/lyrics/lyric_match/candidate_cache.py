"""在线匹配候选结果磁盘缓存（进程级单例）——覆盖 search+detail 阶段。

payload_cache 缓存的是 `fetch_lyrics` 的 raw payload（一首歌的歌词原文），
但在线匹配的耗时大头在更上层：`resolve_candidates` 跑每个 provider 的
`search` + `detail`——NetEase 6 次 cloudsearch + 1 次 song/detail，QQ 5 次
client_search_cp，单次 8-20s。同一首歌第二次点「在线匹配」原封不动重跑这
十几条网络请求，payload 缓存只省掉了最后的拉词往返（几百毫秒），体感
「一样慢」。

本模块在 `provider.search + provider.detail` 层做跨请求候选缓存：

- **键** = provider.source + ":" + 查询指纹（title|artist|album|duration_ms|limit
  归一化后的 sha1 前 16 字符）。搜索词变体是 provider 内部细节（同 q 永远
  生成同一组变体），指纹用 q 本身的四个字段 + limit 即可。duration 纳入
  指纹：netease search_match 用 duration 筛选，不同 rip 的 duration 不同
  → 视为不同查询（不命中，正确）。
- **值** = `search` + `detail` 后的 Candidate 列表（dataclasses.asdict 序列化，
  含 raw；读回用 Candidate(**d) 重建）。缓存整个 search+detail 合并结果，
  把 netease 的 song/detail 网络往返也一并省掉（QQ detail 是 no-op）。
- **TTL** = 7 天，对齐 payload_cache。provider 侧候选数据会变（网易/QQ 上
  架新版本、改词），缓存不能永久。TTL 靠文件 mtime。
- **介质** = 磁盘 JSON，目录 = <db_dir>/lyric_cache/cands/，紧挨 payload
  缓存，同属「Lyra 内部数据」，不污染用户音乐库。重启不丢、删目录即清理。

**缓存语义**：
- 成功候选列表（含空列表——「搜不到」也是稳定结果）→ 缓存。空列表缓存省
  掉对「这歌搜不到」的反复探测。
- search/detail 抛异常的 provider → 不缓存（`resolve_candidates` 自己 try/
  except 跳过该 provider，缓存层在异常路径不写入），允许下次重试。

注入点在 `resolve_candidates`（runner.py）——给每个 provider 的
`search`+`detail` 套 `cached_search_detail` helper。scoring/decision 不变
（命中缓存后照常 score_candidate 打分，打分是纯 CPU）。零决策回归。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from backend.lyrics.lyric_match.types import Candidate, TrackQuery

logger = logging.getLogger(__name__)

# TTL：7 天，对齐 payload_cache。provider 侧候选数据会变。
_TTL = timedelta(days=7)

# 同 key 并发回源防击穿（单 worker 下 search 是 await，两次同 q 的并发请求
# 可能同时 miss → 都回源）。Lock 让第二个等第一个写完再读缓存。
_LOCK = asyncio.Lock()


def _fingerprint(q: TrackQuery, limit: int) -> str:
    """查询指纹：title|artist|album|duration_ms|limit 归一化后 sha1 前 16 字符。

    归一化：strip + 折叠空白 + lower。duration 取整毫秒（浮点抖动不致命中失效）。
    空字段保留为空串，不跳过——title 空 vs title 有值是不同查询。
    """
    def norm(s: str) -> str:
        return " ".join(s.split()).lower()

    dur_ms = ""
    if q.duration is not None:
        # 取整毫秒：同一首歌不同 rip 差几个 ms 不命中是正确的（duration 影响
        # search_match 筛选）；但浮点尾数抖动不该破坏命中，取整抹掉。
        dur_ms = str(int(round(q.duration * 1000)))
    raw = "|".join([
        norm(q.title), norm(q.artist), norm(q.album), dur_ms, str(limit),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class CandidateCache:
    """磁盘候选列表缓存。键 = (source, fingerprint)，值 = Candidate[] 的 JSON。

    进程级单例（get_candidate_cache），不挂 provider 实例——provider 每次请求
    新建实例（lyrics_match_routes._build_providers）。
    """

    def __init__(self, root: Path, ttl: timedelta = _TTL) -> None:
        self._root = root
        self._ttl = ttl
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, source: str, fp: str) -> Path:
        # source 规整成 netease/qq（_build_providers 白名单），fp 是 sha1 hex。
        return self._root / f"{source}_{fp}.json"

    async def get(self, source: str, q: TrackQuery, limit: int) -> list[Candidate] | None:
        """命中返回 detail 后的 Candidate 列表，miss/过期/损坏返回 None（回源）。"""
        p = self._path(source, _fingerprint(q, limit))
        try:
            if not p.is_file():
                return None
            age = datetime.now().timestamp() - p.stat().st_mtime
            if age > self._ttl.total_seconds():
                return None  # 过期：不主动删，下次 set 时 replace 覆盖
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return None
            # 重建 Candidate：asdict 的逆运算。raw 字段是 dict，原样回填。
            out: list[Candidate] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                out.append(Candidate(**_filter_candidate_fields(item)))
            return out
        except Exception:
            logger.warning("candidate cache read failed: %s", p, exc_info=True)
            return None  # 缓存损坏 = 回源，不让匹配崩

    async def set(
        self, source: str, q: TrackQuery, limit: int, cands: list[Candidate],
    ) -> None:
        """写候选列表。空列表也缓存（「搜不到」是稳定结果，省重复探测）。"""
        async with _LOCK:
            p = self._path(source, _fingerprint(q, limit))
            # 原子写：tmp + replace，避免并发读到半截 JSON
            tmp = p.with_suffix(".json.tmp")
            try:
                tmp.write_text(
                    json.dumps([asdict(c) for c in cands], ensure_ascii=False),
                    encoding="utf-8",
                )
                tmp.replace(p)
            except Exception:
                logger.warning("candidate cache write failed: %s", p, exc_info=True)
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass


def _filter_candidate_fields(d: dict[str, Any]) -> dict[str, Any]:
    """从缓存 dict 过滤出 Candidate 构造函数接受的字段。

    防御性：缓存写入是 asdict（字段全），但若未来 Candidate 加/减字段，
    旧缓存 dict 可能有多余字段 → Candidate(**d) 报 TypeError。这里显式白名单，
    让旧缓存能 graceful 退化（多余字段丢弃，缺失字段走 dataclass 默认值）。
    """
    import dataclasses
    fields = {f.name for f in dataclasses.fields(Candidate)}
    return {k: v for k, v in d.items() if k in fields}


# ---------------------------------------------------------------------------
# 模块级单例工厂
# ---------------------------------------------------------------------------

_INSTANCE: CandidateCache | None = None


def get_candidate_cache() -> CandidateCache:
    """进程级单例。lazy 建目录——第一次用时按 db 位置定缓存目录。

    目录 = <db_path 的目录>/lyric_cache/cands/。与 payload_cache 同根
    （<db_dir>/lyric_cache/）下的 cands 子目录，同属「Lyra 内部数据」。
    """
    global _INSTANCE
    if _INSTANCE is None:
        from backend.config import get_settings

        db = get_settings().db_path_resolved()
        _INSTANCE = CandidateCache(db.parent / "lyric_cache" / "cands")
    return _INSTANCE


def reset_candidate_cache_for_test(root: Path | None) -> None:
    """测试用：重置单例到指定目录（None = 清掉单例，下次 get 重建到真实 db 旁）。"""
    global _INSTANCE
    if root is None:
        _INSTANCE = None
    else:
        _INSTANCE = CandidateCache(Path(root))
