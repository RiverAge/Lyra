"""Lyra 歌词在线匹配路由。

端点：
- GET /api/lyrics/{track_id}/match?providers=netease,qq
  从 store 取 track → read_audio_query（读音频 tag 的 title/artist/album/duration）
  → 在线多源匹配（网易 weapi + QQ QRC）→ 返回候选列表 + 最佳匹配 TTML。

  decision: accept / review / reject / not_found
  - accept: 高分且与次优拉开 gap → 可直接采用
  - review: 中等置信或同分多候选 → 人工复核
  - reject: 低分
  - not_found: 无候选

  best_ttml: 当 decision 为 accept/review 且最佳候选有真实歌词时，返回
  该候选的 TTML 字符串（网易 yrc/lrc 或 QQ QRC 转换而来）。否则 null。

路径安全、store 校验、错误码复用 apple_routes / credits_routes 的
_resolve_track 模式（§3.3 行为一致性）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from backend.config import get_settings
from backend.index.store import get_store
from backend.lyrics.lyric_match.converters import payload_to_ttml, qrc_xml_to_ttml
from backend.lyrics.lyric_match.lyrics_io import lyric_payload_has_text, read_audio_query
from backend.lyrics.lyric_match.providers import LyricProvider
from backend.lyrics.lyric_match.runner import match_query_with_payload
from backend.lyrics.lyric_match.types import Candidate

logger = logging.getLogger(__name__)

lyrics_router = APIRouter(tags=["lyrics"])

# 已知 provider slug → 构造器。新增源时在此注册。
_PROVIDER_FACTORIES = {
    "netease": "backend.lyrics.lyric_match.providers.netease.NeteaseProvider",
    "qq": "backend.lyrics.lyric_match.providers.qq.QqProvider",
}

_DEFAULT_PROVIDERS = ("netease", "qq")
_DEFAULT_LIMIT = 12
_DEFAULT_TOP_N = 10


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


async def _resolve_track(track_id: str) -> tuple[Path, dict[str, object]]:
    """解析 track_id 并验证路径安全。

    复用 apple_routes / credits_routes 的 _resolve_track 模式：
    - 422 — 非数字 track_id
    - 503 — store 未初始化 / library root 未配置
    - 404 — track 不存在 / 路径不在库根下 / 文件不存在

    Returns:
        (file_path, row_dict)
    """
    try:
        rowid = int(track_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid track ID")

    store = get_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Database not initialized")

    row = await store.get_track_by_id(rowid)
    if row is None:
        raise HTTPException(status_code=404, detail="Track not found")

    # 路径安全校验
    track_path = Path(row["path"]).resolve()
    settings = get_settings()
    library_root = settings.music_library_path()
    if library_root is None:
        raise HTTPException(status_code=503, detail="Library root not configured")
    if not track_path.is_relative_to(library_root.resolve()):
        raise HTTPException(status_code=404, detail="Track not found")

    if not track_path.is_file():
        raise HTTPException(status_code=404, detail="Track not found")

    return track_path, dict(row)


def _build_providers(provider_slugs: list[str]) -> list[LyricProvider]:
    """根据 slug 列表实例化 providers。未知 slug → 400。

    调用方负责 close() 释放 httpx.AsyncClient。
    """
    from importlib import import_module

    providers: list[LyricProvider] = []
    for slug in provider_slugs:
        factory_path = _PROVIDER_FACTORIES.get(slug)
        if factory_path is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown provider: {slug} "
                    f"(supported: {', '.join(sorted(_PROVIDER_FACTORIES))})"
                ),
            )
        module_path, class_name = factory_path.rsplit(".", 1)
        module = import_module(module_path)
        provider_cls = getattr(module, class_name)
        providers.append(provider_cls())
    return providers


async def _close_providers(providers: list[LyricProvider]) -> None:
    """关闭 providers 内部的 httpx.AsyncClient（避免连接泄漏）。"""
    for p in providers:
        close = getattr(p, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:
                logger.warning("Failed to close lyric provider %r", p, exc_info=True)


def _best_ttml(
    best_payload: dict[str, object] | None,
    lyric_source_slug: str | None,
) -> str | None:
    """把最佳候选的原始歌词负载转成 TTML。

    网易（含 lrc/yrc）→ payload_to_ttml；QQ（_qrc_xml）→ qrc_xml_to_ttml。
    无负载 / 无真实歌词文本 → None。转换异常 → None（路由不崩，记 warning）。
    """
    if best_payload is None or lyric_source_slug is None:
        return None
    try:
        if lyric_source_slug == "qq":
            qrc_xml = str(best_payload.get("_qrc_xml") or "")
            if not qrc_xml:
                return None
            return qrc_xml_to_ttml(qrc_xml, "qq")
        # netease（及未来其他 JSON 负载源）
        if not lyric_payload_has_text(best_payload):
            return None
        return payload_to_ttml(best_payload, lyric_source_slug)
    except Exception as e:
        logger.warning("Failed to convert best lyric payload to TTML: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# GET /lyrics/{track_id}/match
# ---------------------------------------------------------------------------


@lyrics_router.get("/lyrics/{track_id}/match")
async def lyrics_match(
    track_id: str,
    providers: str = Query(
        default=",".join(_DEFAULT_PROVIDERS),
        description="逗号分隔的 provider slug，如 netease,qq",
    ),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=50, description="每源候选召回上限"),
    top_n: int = Query(default=_DEFAULT_TOP_N, ge=1, le=50, description="返回候选数上限"),
) -> dict[str, object]:
    """在线歌词匹配。

    流程：
    1. _resolve_track 验证 track_id + 路径安全（422/503/404）
    2. read_audio_query 读音频 tag（mutagen）→ TrackQuery(title/artist/album/duration)
    3. match_query_with_payload 多源扇出 + 统一打分 + QQ 回退 → 候选列表 + 原始最佳负载
    4. best_ttml = 转换最佳候选歌词负载为 TTML（网易 yrc/lrc 或 QQ QRC）

    Returns:
        - 200 + {track_id, decision, reason, best, candidates, lyrics, best_ttml}
        - 422 — 非数字 track_id
        - 404 — track 不存在 / 路径越界 / 文件不存在
        - 503 — store 未初始化 / library root 未配置
        - 400 — 未知 provider slug
    """
    track_path, _ = await _resolve_track(track_id)

    # read_audio_query 走 mutagen 读 tag；文件损坏 / 不支持扩展名 → 503
    try:
        query = read_audio_query(track_path, with_md5=False)
    except Exception as e:
        logger.warning("read_audio_query failed for %s: %s", track_path, e, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail=f"Failed to read track metadata: {e}",
        ) from e

    # 解析 providers 参数（去重 + 保留顺序）
    slug_list = [s.strip() for s in providers.split(",") if s.strip()]
    if not slug_list:
        raise HTTPException(status_code=400, detail="No providers specified")
    # 顺序去重
    seen: set[str] = set()
    ordered_slugs: list[str] = []
    for s in slug_list:
        if s not in seen:
            seen.add(s)
            ordered_slugs.append(s)

    provider_instances = _build_providers(ordered_slugs)
    try:
        result, best_payload, lyric_source_slug = await match_query_with_payload(
            provider_instances,
            query,
            limit=limit,
            top_n=top_n,
        )
    finally:
        await _close_providers(provider_instances)

    best_ttml = _best_ttml(best_payload, lyric_source_slug)

    return {
        "track_id": track_id,
        "decision": result.get("decision"),
        "reason": result.get("reason"),
        "best": result.get("best"),
        "candidates": result.get("candidates"),
        "lyrics": result.get("lyrics"),
        "lyric_source": result.get("lyric_source"),
        "best_ttml": best_ttml,
    }


# ---------------------------------------------------------------------------
# GET /lyrics/{track_id}/preview — 按候选拉取 TTML 预览
# ---------------------------------------------------------------------------


@lyrics_router.get("/lyrics/{track_id}/preview")
async def lyrics_preview(
    track_id: str,
    source: str = Query(description="来源 slug：netease / qq"),
    candidate_id: int = Query(description="候选歌曲 id（match 端点返回的 candidate.id）"),
) -> dict[str, object]:
    """按候选拉取 TTML 预览。

    用于前端在「其他候选」里点选任意候选时，按需拉取该候选的歌词 TTML，
    挂载到预览区（不重跑匹配，只按 candidate.id 取词）。

    依赖：provider.fetch_lyrics 只读 candidate.id（已确认 netease.py/qq.py），
    所以只需 {id, source} 重建最小 Candidate 即可。

    错误码：
    - 422 — 非数字 track_id（candidate_id 已由 int Query 保证）
    - 404 — track 不存在 / 路径越界
    - 400 — 未知 source slug
    - 503 — store 未初始化 / library root 未配置
    """
    # 校验 track 存在 + 路径安全（预览不读音频 tag，丢弃 track_path）
    await _resolve_track(track_id)

    # slug 白名单：candidate_to_dict 已规整成 netease/qq，这里拒绝其余
    if source not in ("netease", "qq"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source: {source} (supported: netease, qq)",
        )

    provider_instances = _build_providers([source])
    try:
        # fetch_lyrics 只读 candidate.id；source 填 slug 仅供 provider 路由参考
        minimal = Candidate(
            id=candidate_id,
            title="",
            artists=[],
            album="",
            duration_ms=None,
            source=source,
        )
        # 单 provider 场景：直接取第一个（_build_providers 保证按 slug 构造）
        provider = provider_instances[0]
        payload = await provider.fetch_lyrics(minimal)
    finally:
        await _close_providers(provider_instances)

    ttml = _best_ttml(payload, source)

    return {
        "track_id": track_id,
        "candidate_id": candidate_id,
        "source": source,
        "ttml": ttml,
    }
