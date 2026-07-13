"""Apple song_id 提取——单一收敛口径。

原 apple_routes / credits_routes 各持一份 _extract_song_id 且口径不一致：
- apple 版查 cnID 精确 + freeform `----:com.apple.iTunes:songId`
- credits 版只查 cnID（大小写不敏感），漏 freeform

这是可重复扩散的结构性回归口子（§3.5.5 反过度设计 / §3.2 业务口径收敛）。
本模块提供单一提取函数，两 route 共用 import，删掉各自副本。

读取策略优先级（设计决策，依据见各分支注释）：
1. "cnID" — MP4 标准 atom，scanner 通用 tag 循环自动捕获，是 Apple Music 官方
   song ID 字段。优先取它，值权威且与 amp-api path 一致。
2. "----:com.apple.iTunes:songId" — freeform atom，同样被 scanner 捕获。
   旧文件/第三方工具写入的变体，作为 cnID 缺失时的兜底。
3. 大小写不敏感兜底：scanner 写入历史遗留可能产生 "CNID"/"cnid" 等变体 key
   （mutagen MP4 freeform 区分大小写，但标准 atom 亦可能出现大小写变体）。
   精确匹配未命中后，遍历 keys 做大小写不敏感匹配，兼容历史写入。
   仅在精确匹配都未命中时触发，不改变正常路径行为。

输入为已解析的 tag_map dict（mutagen key → list[str]）。
调用方负责 JSON 解析与类型校验（与 apple_routes 原口径一致）。
"""

from __future__ import annotations


def extract_song_id(tag_map: dict[str, object]) -> str | None:
    """从 track 的 tag_map 提取 Apple song_id。

    读取策略优先级（详见模块 docstring）：
    1. cnID 精确匹配
    2. freeform `----:com.apple.iTunes:songId` 精确匹配
    3. 大小写不敏感兜底（兼容 scanner 历史写入的变体 key）

    Args:
        tag_map: 从 store 读取的 tag_map dict（mutagen key → list[str]）
            调用方需保证已通过 isinstance(tag_map, dict) 校验。

    Returns:
        song_id 字符串，或 None（标签中无 song_id）
    """
    # 优先 cnID（精确）
    cnid = tag_map.get("cnID")
    if isinstance(cnid, list) and cnid:
        return str(cnid[0])

    # 其次 freeform songId（精确）
    song_id_val = tag_map.get("----:com.apple.iTunes:songId")
    if isinstance(song_id_val, list) and song_id_val:
        return str(song_id_val[0])

    # 大小写不敏感兜底：兼容 scanner 历史写入的变体 key（"CNID"/"cnid" 等）
    for key, values in tag_map.items():
        if not isinstance(values, list) or not values:
            continue
        key_lower = key.lower()
        if key_lower == "cnid":
            return str(values[0])
        if key_lower == "----:com.apple.itunes:songid":
            return str(values[0])

    return None
