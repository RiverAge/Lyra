"""Lyra 元数据 before/after 对比模块。

纯函数，不碰文件系统。
输入本地 tag_map（scanner 存的 JSON 反序列化）和
权威字段（auth_fields），输出每字段的对比状态。

字段对齐：从 writer.py 导入 FIELD_MAP + 反向映射表，
确保两处映射互逆一致。
"""

from __future__ import annotations

from typing import TypedDict

from backend.meta.writer import (
    FIELD_MAP,
    FLAC_KEY_TO_SEMANTIC,
    MP3_KEY_TO_SEMANTIC,
    MP4_KEY_TO_SEMANTIC,
)


class FieldDiff(TypedDict, total=False):
    """单字段的 before/after 对比结果。"""
    field: str
    local_value: list[str] | None
    auth_value: list[str] | None
    status: str  # "same" | "missing_local" | "missing_auth" | "different"


class DiffResult(TypedDict):
    """完整对比结果。"""
    before: dict[str, list[str] | None]  # 语义字段名 → 本地值（None 表示缺失）
    after: dict[str, list[str] | None]   # 语义字段名 → 权威值
    diffs: list[FieldDiff]


# ---------------------------------------------------------------------------
# 格式检测辅助
# ---------------------------------------------------------------------------


def _detect_codec_from_tag_map(tag_map: dict[str, object]) -> str | None:
    """从 tag_map 的 key 推断格式。

    看 key 特征判断 MP4/FLAC/MP3：
    - MP4: key 含 © / ----:com.apple.iTunes:
    - FLAC: key 全小写字母 / 下划线
    - MP3: key 大写字母 + 数字（TIT2 等）

    兜底：若 key 在 MP4_KEY_TO_SEMANTIC 中命中更多返回 "alac"，
    在 FLAC_KEY_TO_SEMANTIC 中命中更多返回 "flac"。
    """
    if not tag_map:
        return None

    keys = list(tag_map.keys())
    mp4_hits = sum(1 for k in keys if k.startswith("©") or k.startswith("----:com.apple.iTunes"))
    flac_hits = sum(1 for k in keys if k in FLAC_KEY_TO_SEMANTIC)
    mp3_hits = sum(1 for k in keys if k in MP3_KEY_TO_SEMANTIC)

    if mp4_hits >= flac_hits and mp4_hits >= mp3_hits:
        return "alac"
    elif flac_hits >= mp3_hits:
        return "flac"
    elif mp3_hits > 0:
        return "mp3"
    return None


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------


def _get_semantic_key_map(codec: str) -> dict[str, str]:
    """获取 codec 对应的 mutagen→semantic 反向映射。"""
    if codec == "alac":
        return MP4_KEY_TO_SEMANTIC
    elif codec == "flac":
        return FLAC_KEY_TO_SEMANTIC
    elif codec == "mp3":
        return MP3_KEY_TO_SEMANTIC
    return {}


def _get_mutagen_key(semantic: str, codec: str) -> str | None:
    """获取语义字段名在当前 codec 下的 mutagen key。"""
    mapping = FIELD_MAP.get(semantic)
    if mapping is None:
        return None
    idx = {"alac": 0, "flac": 1, "mp3": 2}.get(codec)
    if idx is None:
        return None
    return mapping[idx]


def compute_diff(
    local_tag_map: dict[str, object],
    auth_fields: dict[str, list[str]],
) -> DiffResult:
    """计算 before/after 对比。

    根据 local_tag_map 的 key 特征自动推断 codec。
    然后遍历语义字段（取 local 和 auth 的并集），对每个字段：

    - local 有值 / auth 有值且相等 → status = "same"
    - local 有值 / auth 无此字段  → status = "missing_auth"
    - local 无值 / auth 有值      → status = "missing_local"
    - local 有值 / auth 有值但不等 → status = "different"

    Args:
        local_tag_map: scanner 存的 tag_map 反序列化（mutagen 原生 key → list[str]）。
        auth_fields: 权威元数据（语义字段名 → list[str]）。

    Returns:
        DiffResult 结构，含 before/after/diffs。
    """
    codec = _detect_codec_from_tag_map(local_tag_map)
    if codec is None:
        # 无法判定 codec — 仅返回 auth 字段作为 after
        before: dict[str, list[str] | None] = {}
        after: dict[str, list[str] | None] = {}
        diffs: list[FieldDiff] = []
        all_sem = set(auth_fields.keys())
        for sem in sorted(all_sem):
            auth_val = auth_fields.get(sem)
            after[sem] = auth_val
            before[sem] = None
            if auth_val:
                diffs.append(FieldDiff(
                field=sem, local_value=None, auth_value=auth_val,
                status="missing_local",
            ))
        return DiffResult(before=before, after=after, diffs=diffs)

    key_map = _get_semantic_key_map(codec)

    # 将所有 local 的 mutagen key 映射为语义字段名
    local_sem: dict[str, list[str]] = {}
    for muta_key, raw_val in local_tag_map.items():
        if muta_key in key_map:
            sem = key_map[muta_key]
            local_sem[sem] = _to_string_list(raw_val)
        elif muta_key.startswith("----:com.apple.iTunes:"):
            # freeform key: 尝试直接匹配
            suffix = muta_key.rsplit(":", 1)[-1].lower()
            # 在 KEY_TO_SEMANTIC 中找
            found = False
            for k, s in MP4_KEY_TO_SEMANTIC.items():
                k_suffix = k.rsplit(":", 1)[-1].lower() if ":" in k else k.lower()
                if k_suffix == suffix:
                    local_sem[s] = _to_string_list(raw_val)
                    found = True
                    break
            if not found:
                local_sem[muta_key] = _to_string_list(raw_val)
        else:
            # 无法映射到语义字段的保留原始 mutagen key
            local_sem[muta_key] = _to_string_list(raw_val)

    # 取语义字段的并集
    all_semantic_fields: set[str] = set()
    for k in local_sem:
        # 只考虑能映射的字段
        if k in FIELD_MAP:
            all_semantic_fields.add(k)
    for k in auth_fields:
        all_semantic_fields.add(k)

    before = {}
    after = {}
    diffs = []

    for sem in sorted(all_semantic_fields):
        local_val = local_sem.get(sem)
        auth_val = auth_fields.get(sem)

        before[sem] = local_val
        after[sem] = auth_val if auth_val else None

        if local_val is not None and auth_val is not None:
            if local_val == auth_val:
                status = "same"
            else:
                status = "different"
        elif local_val is not None and auth_val is None:
            status = "missing_auth"
        elif local_val is None and auth_val is not None:
            status = "missing_local"
        else:
            # 两者都无值（理论上不会出现）
            continue

        diffs.append(FieldDiff(
            field=sem,
            local_value=local_val,
            auth_value=auth_val,
            status=status,
        ))

    return DiffResult(before=before, after=after, diffs=diffs)


def _to_string_list(raw_val: object) -> list[str]:
    """将 tag_map 中的值规范化为字符串列表。

    兼容 scanner 输出的 tag_map JSON 反序列化后的类型：
    - list[str] → 直接返回
    - 其他（list[object] 等）→ 逐个 str() 转换
    """
    if isinstance(raw_val, list):
        return [str(v) for v in raw_val]
    return [str(raw_val)]