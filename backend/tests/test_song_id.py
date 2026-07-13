"""测试——backend/meta/song_id.py 提取口径收敛。

覆盖 P1-1 去重后的单一 extract_song_id：
- cnID 精确优先
- freeform `----:com.apple.iTunes:songId` 兜底（原 credits 版漏的口子）
- 大小写变体 key（CNID/cnid）兜底
- cnID + freeform 同时存在 → cnID 胜出
- 两 key 都无 → None
- 空 list / 非 list 值 → None
- 空 tag_map → None

P1-1 修复前：apple_routes 查 cnID 精确 + freeform；credits_routes 只查 cnID
（大小写不敏感），漏 freeform。收敛到 meta.song_id 后两 route 共用，
credits 补上 freeform 是修正不是回归。
"""

from __future__ import annotations

from backend.meta.song_id import extract_song_id

# ---------------------------------------------------------------------------
# cnID 精确优先
# ---------------------------------------------------------------------------


class TestExtractSongIdCnId:
    """cnID 精确匹配路径。"""

    def test_cnid_only(self) -> None:
        """tag_map 只有 cnID → 返回 cnID 值。"""
        tag_map = {"cnID": ["1234567890"]}
        assert extract_song_id(tag_map) == "1234567890"

    def test_cnid_and_freeform_returns_cnid(self) -> None:
        """cnID + freeform 同时存在 → cnID 胜出（优先级 1）。"""
        tag_map = {
            "cnID": ["111"],
            "----:com.apple.iTunes:songId": ["222"],
        }
        assert extract_song_id(tag_map) == "111"


# ---------------------------------------------------------------------------
# freeform songId 兜底
# ---------------------------------------------------------------------------


class TestExtractSongIdFreeform:
    """freeform `----:com.apple.iTunes:songId` 路径（原 credits 版漏的口子）。"""

    def test_freeform_only(self) -> None:
        """tag_map 无 cnID 但有 freeform songId → 返回 freeform 值。

        P1-1 修正点：原 credits_routes _extract_song_id 只查 cnID，
        此场景会返回 None（漏 freeform）。
        """
        tag_map = {"----:com.apple.iTunes:songId": ["9876543210"]}
        assert extract_song_id(tag_map) == "9876543210"


# ---------------------------------------------------------------------------
# 大小写变体兜底
# ---------------------------------------------------------------------------


class TestExtractSongIdCaseInsensitive:
    """scanner 历史写入的大小写变体 key 兜底。"""

    def test_cnid_uppercase_key(self) -> None:
        """key 为大写 CNID → 大小写不敏感兜底命中。"""
        tag_map = {"CNID": ["333"]}
        assert extract_song_id(tag_map) == "333"

    def test_cnid_lowercase_key(self) -> None:
        """key 为小写 cnid → 大小写不敏感兜底命中。"""
        tag_map = {"cnid": ["444"]}
        assert extract_song_id(tag_map) == "444"

    def test_freeform_uppercase_key(self) -> None:
        """freeform key 大写变体 → 大小写不敏感兜底命中。"""
        tag_map = {"----:COM.APPLE.ITUNES:SONGID": ["555"]}
        assert extract_song_id(tag_map) == "555"

    def test_cnid_exact_beats_case_variant(self) -> None:
        """cnID 精确 + cnid 变体同时存在 → 精确优先。"""
        tag_map = {"cnID": ["exact"], "cnid": ["variant"]}
        assert extract_song_id(tag_map) == "exact"


# ---------------------------------------------------------------------------
# 无 song_id → None
# ---------------------------------------------------------------------------


class TestExtractSongIdNone:
    """两 key 都无 / 无效值 → None。"""

    def test_both_keys_absent(self) -> None:
        """两 key 都无 → None。"""
        tag_map = {"©nam": ["Title"], "©ART": ["Artist"]}
        assert extract_song_id(tag_map) is None

    def test_empty_tag_map(self) -> None:
        """空 tag_map → None。"""
        assert extract_song_id({}) is None

    def test_cnid_empty_list(self) -> None:
        """cnID 为空 list → None（不命中，继续查 freeform）。"""
        tag_map = {"cnID": []}
        assert extract_song_id(tag_map) is None

    def test_cnid_non_list_value(self) -> None:
        """cnID 非 list（如 str）→ None。

        scanner 写入应总是 list[str]，但兜底校验非 list 不崩。
        """
        tag_map = {"cnID": "not-a-list"}
        assert extract_song_id(tag_map) is None

    def test_cnid_empty_and_freeform_present(self) -> None:
        """cnID 空 list + freeform 有值 → freeform 命中。"""
        tag_map = {
            "cnID": [],
            "----:com.apple.iTunes:songId": ["666"],
        }
        assert extract_song_id(tag_map) == "666"
