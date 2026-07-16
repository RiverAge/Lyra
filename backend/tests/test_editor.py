"""测试——逐字歌词编辑器(editor + editor_routes)。

覆盖:
- parse 含 span 的 TTML → 结构正确
- serialize → parse round-trip 等价(审计规则 §3.9,审计重点)
- serialize 字节对齐 converters._build_ttml(时间格式不漂移)
- update_span_time / update_line_time 改单个时间正确(不可变,返回新 doc)
- 时间格式与 converters._format_ttml_time 一致
- 路由:GET 返回 doc / PATCH 更新写回 / POST 全量替换 / 404 / 400 / 422 / 503
"""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.index.store import IndexStore, set_store
from backend.lyrics.editor import (
    Line,
    LyricDoc,
    Span,
    docs_equal,
    format_ttml_time,
    parse_ttml,
    parse_ttml_time,
    serialize_ttml,
    update_line_time,
    update_span_time,
)
from backend.server.editor_routes import editor_router

# converters.py 位于参考项目,测试时按需加入 sys.path 比对时间格式
_CONVERTERS_PATH = (
    r"C:/Users/Mercury/Downloads/AppleMusicDecrypt-Windows/tools"
)


# ---------------------------------------------------------------------------
# TTML fixtures
# ---------------------------------------------------------------------------


# 一份含 span + 纯文本行的 TTML(由 converters._build_ttml 生成,作为 ground-truth)
# 长 <p> 行用隐式拼接拆分,运行时拼接结果与 converters 输出字节一致。
_TTML_WITH_SPANS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<tt xmlns="http://www.w3.org/ns/ttml" '
    'xmlns:amdl="https://github.com/AppleMusicDecrypt/lyrics" '
    'xml:lang="und">\n'
    "  <head>\n"
    "    <metadata>\n"
    "      <amdl:source>netease</amdl:source>\n"
    "    </metadata>\n"
    "  </head>\n"
    '  <body xml:lang="und">\n'
    '    <div role="main" xml:lang="und">\n'
    '      <p key="L1" begin="00:00:00.000" end="00:00:05.000">'
    '<span begin="00:00:00.000" end="00:00:00.800">你</span>'
    '<span begin="00:00:00.800" end="00:00:01.600">好</span>'
    "</p>\n"
    '      <p key="L2" begin="00:00:05.000" end="00:00:10.000">纯文本行</p>\n'
    "    </div>\n"
    "  </body>\n"
    "</tt>\n"
)


def _make_doc() -> LyricDoc:
    """构造与 _TTML_WITH_SPANS 对应的 LyricDoc。"""
    return LyricDoc(
        lines=[
            Line(
                key="L1",
                begin_ms=0,
                end_ms=5000,
                spans=[
                    Span(text="你", begin_ms=0, end_ms=800),
                    Span(text="好", begin_ms=800, end_ms=1600),
                ],
            ),
            Line(key="L2", begin_ms=5000, end_ms=10000, text="纯文本行"),
        ],
        source="netease",
    )


# ---------------------------------------------------------------------------
# parse 测试
# ---------------------------------------------------------------------------


class TestParse:
    """TTML XML → LyricDoc 解析测试。"""

    def test_parse_spans_correct(self) -> None:
        """parse 含 span 的 TTML → 结构正确(key/begin/end/text/spans)。"""
        doc = parse_ttml(_TTML_WITH_SPANS)
        assert doc.source == "netease"
        assert len(doc.lines) == 2

        line1 = doc.lines[0]
        assert line1.key == "L1"
        assert line1.begin_ms == 0
        assert line1.end_ms == 5000
        assert len(line1.spans) == 2
        assert line1.spans[0].text == "你"
        assert line1.spans[0].begin_ms == 0
        assert line1.spans[0].end_ms == 800
        assert line1.spans[1].text == "好"
        assert line1.spans[1].begin_ms == 800
        assert line1.spans[1].end_ms == 1600

    def test_parse_plain_text_line(self) -> None:
        """无 span 的 p → spans 为空,text 为纯文本。"""
        doc = parse_ttml(_TTML_WITH_SPANS)
        line2 = doc.lines[1]
        assert line2.key == "L2"
        assert line2.spans == []
        assert line2.text == "纯文本行"

    def test_parse_invalid_xml_raises(self) -> None:
        """非法 XML → ValueError(不静默吞)。"""
        with pytest.raises(ValueError, match="Invalid TTML XML"):
            parse_ttml("<not-closed>")

    def test_parse_empty_body(self) -> None:
        """空 body(div 无 p)→ 0 lines。"""
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<tt xmlns="http://www.w3.org/ns/ttml" '
            'xmlns:amdl="https://github.com/AppleMusicDecrypt/lyrics" '
            'xml:lang="und">'
            "<head><metadata><amdl:source>x</amdl:source></metadata></head>"
            '<body xml:lang="und"><div></div></body></tt>'
        )
        doc = parse_ttml(xml)
        assert doc.lines == []
        assert doc.source == "x"

    def test_parse_missing_source_defaults(self) -> None:
        """无 amdl:source → 默认 'netease'(宽容)。"""
        xml = (
            '<tt xmlns="http://www.w3.org/ns/ttml" xml:lang="und">'
            "<head><metadata></metadata></head>"
            '<body xml:lang="und"><div>'
            '<p key="L" begin="00:00:00.000" end="00:00:01.000">t</p>'
            "</div></body></tt>"
        )
        doc = parse_ttml(xml)
        assert doc.source == "netease"

    def test_parse_special_chars_escaped(self) -> None:
        """含 & < > 的文本正确反转义。"""
        xml = (
            '<tt xmlns="http://www.w3.org/ns/ttml" xml:lang="und">'
            '<body xml:lang="und"><div>'
            '<p key="L" begin="00:00:00.000" end="00:00:01.000">'
            "a&amp;b&lt;c&gt;d"
            "</p></div></body></tt>"
        )
        doc = parse_ttml(xml)
        assert doc.lines[0].text == "a&b<c>d"


# ---------------------------------------------------------------------------
# serialize + round-trip 测试(审计重点 §3.9)
# ---------------------------------------------------------------------------


class TestSerializeRoundTrip:
    """serialize → parse round-trip 等价测试。"""

    def test_serialize_byte_identical_to_converters(self) -> None:
        """serialize 输出字节对齐 converters._build_ttml(格式不漂移)。

        防御:编辑器改完写回的 TTML 与下载流程写的格式一致,
        不会因时间格式/转义/骨架差异导致后续解析侧歧义。
        """
        out = serialize_ttml(_make_doc())
        assert out == _TTML_WITH_SPANS

    def test_round_trip_preserves_doc(self) -> None:
        """parse → serialize → parse 再读回,两份 doc 深度相等(§3.9 核心断言)。"""
        doc1 = parse_ttml(_TTML_WITH_SPANS)
        serialized = serialize_ttml(doc1)
        doc2 = parse_ttml(serialized)
        assert docs_equal(doc1, doc2)

    def test_round_trip_byte_stable(self) -> None:
        """serialize 再 serialize:输出稳定(幂等)。"""
        doc = parse_ttml(_TTML_WITH_SPANS)
        once = serialize_ttml(doc)
        twice = serialize_ttml(parse_ttml(once))
        assert once == twice

    def test_round_trip_preserves_span_times(self) -> None:
        """round-trip 后 span 的 begin/end 精确保持(逐字编辑核心)。"""
        doc1 = parse_ttml(_TTML_WITH_SPANS)
        serialized = serialize_ttml(doc1)
        doc2 = parse_ttml(serialized)
        for l1, l2 in zip(doc1.lines, doc2.lines, strict=True):
            assert l1.begin_ms == l2.begin_ms
            assert l1.end_ms == l2.end_ms
            for s1, s2 in zip(l1.spans, l2.spans, strict=True):
                assert s1.begin_ms == s2.begin_ms
                assert s1.end_ms == s2.end_ms
                assert s1.text == s2.text

    def test_round_trip_with_special_chars(self) -> None:
        """含特殊字符(& < > " ')的文本 round-trip 不丢信息。"""
        doc = LyricDoc(
            lines=[
                Line(
                    key="L",
                    begin_ms=0,
                    end_ms=1000,
                    spans=[
                        Span(text='a&b<c>"d\'e', begin_ms=0, end_ms=500),
                    ],
                ),
            ],
            source="qq",
        )
        serialized = serialize_ttml(doc)
        doc2 = parse_ttml(serialized)
        assert docs_equal(doc, doc2)
        assert doc2.lines[0].spans[0].text == 'a&b<c>"d\'e'

    def test_round_trip_with_hours(self) -> None:
        """时间超过 1 小时时 round-trip 精确(小时位不丢)。"""
        doc = LyricDoc(
            lines=[
                Line(
                    key="L",
                    begin_ms=3661500,  # 01:01:01.500
                    end_ms=3662000,
                    text="x",
                ),
            ],
        )
        serialized = serialize_ttml(doc)
        assert "01:01:01.500" in serialized
        doc2 = parse_ttml(serialized)
        assert docs_equal(doc, doc2)
        assert doc2.lines[0].begin_ms == 3661500


# ---------------------------------------------------------------------------
# 时间格式测试(对齐 converters._format_ttml_time)
# ---------------------------------------------------------------------------


class TestTimeFormat:
    """时间格式与 converters._format_ttml_time 一致性测试。"""

    def test_format_zero(self) -> None:
        """0ms → 00:00:00.000。"""
        assert format_ttml_time(0) == "00:00:00.000"

    def test_format_hours(self) -> None:
        """3661500ms → 01:01:01.500(小时位)。"""
        assert format_ttml_time(3661500) == "01:01:01.500"

    def test_format_negative_clamps_to_zero(self) -> None:
        """负数归零(对齐 converters._format_ttml_time)。"""
        assert format_ttml_time(-100) == "00:00:00.000"

    def test_format_millis_padded(self) -> None:
        """毫秒补零到 3 位(50ms → .050,5ms → .005)。"""
        assert format_ttml_time(50).endswith(".050")
        assert format_ttml_time(5).endswith(".005")

    def test_format_matches_converters(self) -> None:
        """format_ttml_time 与 converters._format_ttml_time 字节一致(照搬逻辑)。

        若 converters 不可导入(参考项目不在),跳过——不阻断 CI。
        动态 import(importlib)避免 mypy 静态分析报找不到模块。
        """
        import importlib

        if _CONVERTERS_PATH not in sys.path:
            sys.path.insert(0, _CONVERTERS_PATH)
        try:
            ref_mod = importlib.import_module("lyric_match.converters")
        except ImportError:
            pytest.skip("converters.py reference not available")
        ref = getattr(ref_mod, "_format_ttml_time")
        for ms in [0, 1, 5, 50, 999, 1000, 59999, 60000, 3600000, 3661500, -1, -1000]:
            assert format_ttml_time(ms) == ref(ms)

    def test_parse_round_trip_time(self) -> None:
        """parse_ttml_time(format_ttml_time(ms)) == ms(对称)。"""
        for ms in [0, 1, 5, 50, 999, 1000, 59999, 60000, 3600000, 3661500]:
            assert parse_ttml_time(format_ttml_time(ms)) == ms

    def test_parse_no_millis(self) -> None:
        """无毫秒部分(00:00:01)解析为 1000ms(宽容)。"""
        assert parse_ttml_time("00:00:01") == 1000

    def test_parse_bad_returns_zero(self) -> None:
        """无法解析 → 0(不抛,避免单个坏时间戳阻断整份解析)。"""
        assert parse_ttml_time("garbage") == 0
        assert parse_ttml_time("") == 0


# ---------------------------------------------------------------------------
# 编辑操作测试
# ---------------------------------------------------------------------------


class TestUpdate:
    """update_span_time / update_line_time 测试。"""

    def test_update_span_time_correct(self) -> None:
        """update_span_time 改单个 span 的 begin/end,返回新 doc。"""
        doc = _make_doc()
        new_doc = update_span_time(doc, line_index=0, span_index=1, begin_ms=900, end_ms=1700)
        # 原 doc 不变(不可变)
        assert doc.lines[0].spans[1].begin_ms == 800
        # 新 doc 已更新
        assert new_doc.lines[0].spans[1].begin_ms == 900
        assert new_doc.lines[0].spans[1].end_ms == 1700
        # 其它 span 不受影响
        assert new_doc.lines[0].spans[0].begin_ms == 0
        assert new_doc.lines[0].spans[0].end_ms == 800

    def test_update_span_time_immutability(self) -> None:
        """更新后原 doc 引用未变(不修改原对象)。"""
        doc = _make_doc()
        original = parse_ttml(serialize_ttml(doc))
        _new_doc = update_span_time(doc, 0, 0, 10, 20)
        # 原 doc 结构未变
        assert docs_equal(doc, original)

    def test_update_line_time_correct(self) -> None:
        """update_line_time 改单个 line 的 begin/end。"""
        doc = _make_doc()
        new_doc = update_line_time(doc, line_index=1, begin_ms=6000, end_ms=11000)
        assert doc.lines[1].begin_ms == 5000
        assert new_doc.lines[1].begin_ms == 6000
        assert new_doc.lines[1].end_ms == 11000
        # 其它 line 不变
        assert new_doc.lines[0].begin_ms == 0

    def test_update_span_time_out_of_range_line(self) -> None:
        """line_index 越界 → IndexError。"""
        doc = _make_doc()
        with pytest.raises(IndexError, match="line_index"):
            update_span_time(doc, line_index=99, span_index=0, begin_ms=0, end_ms=1)

    def test_update_span_time_out_of_range_span(self) -> None:
        """span_index 越界 → IndexError(纯文本行无 span)。"""
        doc = _make_doc()
        # line 1 是纯文本行,无 span
        with pytest.raises(IndexError, match="span_index"):
            update_span_time(doc, line_index=1, span_index=0, begin_ms=0, end_ms=1)

    def test_update_line_time_out_of_range(self) -> None:
        """line_index 越界 → IndexError。"""
        doc = _make_doc()
        with pytest.raises(IndexError, match="line_index"):
            update_line_time(doc, line_index=-1, begin_ms=0, end_ms=1)


# ---------------------------------------------------------------------------
# editor_routes 测试 — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """创建含 editor_router 的测试 app(与生产一致:/api 前缀)。"""
    app_fast = FastAPI()
    app_fast.include_router(editor_router, prefix="/api")
    return app_fast


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """返回已绑定测试 app 的 httpx AsyncClient。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# editor_routes 测试 — 辅助
# ---------------------------------------------------------------------------


def _write_sidecar(tmp_path: Path, source: str = "apple") -> Path:
    """在 tmp_path/.lyrics/<source>/ 下写一个 sidecar TTML。

    音频路径:tmp_path/apple/Artist/Album/01 Song.m4a(生产环境布局:首段是来源目录)。
    sidecar_path_for 会去掉首段 apple/,故 sidecar 路径体为 Artist/Album/01 Song。
    apple sidecar:tmp_path/.lyrics/apple/Artist/Album/01 Song.ttml
    netease/qq sidecar:tmp_path/.lyrics/<source>/Artist/Album/01 Song-<source>.ttml
    返回 audio 路径(audio 已创建,sidecar 内容 = _TTML_WITH_SPANS)。
    """
    audio_rel = Path("apple") / "Artist" / "Album" / "01 Song.m4a"
    audio = tmp_path / audio_rel
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"\x00" * 100)
    lyrics_root = tmp_path / ".lyrics"
    if source == "apple":
        sidecar = lyrics_root / "apple" / "Artist" / "Album" / "01 Song.ttml"
    else:
        sidecar = (
            lyrics_root
            / source
            / "Artist"
            / "Album"
            / f"01 Song-{source}.ttml"
        )
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(_TTML_WITH_SPANS, encoding="utf-8")
    return audio


async def _insert_track(store: IndexStore, audio: Path) -> int:
    """插入一条 track 记录指向 audio,返回 rowid。"""
    return await store.insert_track(
        title="Test",
        artist="Artist",
        path=str(audio).replace("\\", "/"),
        codec="alac",
        duration=200000,
    )


# ---------------------------------------------------------------------------
# editor_routes 测试 — GET
# ---------------------------------------------------------------------------


class TestGetRoute:
    """GET /api/lyrics/{track_id}/edit 测试。"""

    async def test_get_returns_doc(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """正常 GET → 200 + span 结构 JSON。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        resp = await client.get(f"/api/lyrics/{rowid}/edit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "netease"
        assert len(body["lines"]) == 2
        line0 = body["lines"][0]
        assert line0["key"] == "L1"
        assert len(line0["spans"]) == 2
        assert line0["spans"][0]["text"] == "你"
        assert line0["spans"][0]["begin_ms"] == 0
        assert line0["spans"][0]["end_ms"] == 800
        # 纯文本行
        assert body["lines"][1]["spans"] == []
        assert body["lines"][1]["text"] == "纯文本行"

    async def test_get_sidecar_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """sidecar 不存在 → 404。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        # 删掉 sidecar
        sidecar = (
            tmp_path / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song.ttml"
        )
        sidecar.unlink()
        rowid = await _insert_track(store, audio)

        resp = await client.get(f"/api/lyrics/{rowid}/edit")
        assert resp.status_code == 404
        assert "sidecar" in resp.text.lower()

    async def test_get_unsupported_source(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """不支持的 source → 400。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        resp = await client.get(f"/api/lyrics/{rowid}/edit?source=spotify")
        assert resp.status_code == 400

    async def test_get_netease_source(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """source=netease → 读 .lyrics/netease/.../-netease.ttml。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "netease")
        rowid = await _insert_track(store, audio)

        resp = await client.get(f"/api/lyrics/{rowid}/edit?source=netease")
        assert resp.status_code == 200
        assert resp.json()["source"] == "netease"

    async def test_get_track_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
    ) -> None:
        """track 不存在 → 404。"""
        resp = await client.get("/api/lyrics/999999/edit")
        assert resp.status_code == 404

    async def test_get_invalid_track_id(self, client: AsyncClient) -> None:
        """非数字 track_id → 422。"""
        resp = await client.get("/api/lyrics/abc/edit")
        assert resp.status_code == 422

    async def test_get_db_unavailable(self, app: FastAPI) -> None:
        """store 未初始化 → 503。"""
        set_store(None)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/api/lyrics/1/edit")
            assert resp.status_code == 503


# ---------------------------------------------------------------------------
# editor_routes 测试 — PATCH
# ---------------------------------------------------------------------------


class TestPatchRoute:
    """PATCH /api/lyrics/{track_id}/edit 测试。"""

    async def test_patch_span_writes_back(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """PATCH 改 span 时间 → 写回 sidecar,再读回验证。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        resp = await client.patch(
            f"/api/lyrics/{rowid}/edit",
            json={
                "line_index": 0,
                "span_index": 1,
                "begin_ms": 900,
                "end_ms": 1700,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["doc"]["lines"][0]["spans"][1]["begin_ms"] == 900
        assert body["doc"]["lines"][0]["spans"][1]["end_ms"] == 1700

        # 再 GET 确认写盘
        resp2 = await client.get(f"/api/lyrics/{rowid}/edit")
        assert resp2.status_code == 200
        spans = resp2.json()["lines"][0]["spans"]
        assert spans[1]["begin_ms"] == 900
        assert spans[1]["end_ms"] == 1700
        # 其它 span 未变
        assert spans[0]["begin_ms"] == 0
        assert spans[0]["end_ms"] == 800

    async def test_patch_line_writes_back(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """PATCH 改 line 时间(span_index=None)→ 写回。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        resp = await client.patch(
            f"/api/lyrics/{rowid}/edit",
            json={
                "line_index": 1,
                "span_index": None,
                "begin_ms": 6000,
                "end_ms": 11000,
            },
        )
        assert resp.status_code == 200
        line1 = resp.json()["doc"]["lines"][1]
        assert line1["begin_ms"] == 6000
        assert line1["end_ms"] == 11000

    async def test_patch_out_of_range_index(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """越界索引 → 400(显式,不 500)。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        resp = await client.patch(
            f"/api/lyrics/{rowid}/edit",
            json={
                "line_index": 99,
                "span_index": 0,
                "begin_ms": 0,
                "end_ms": 1,
            },
        )
        assert resp.status_code == 400
        assert "out of range" in resp.text.lower()

    async def test_patch_sidecar_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """sidecar 不存在 → 404(PATCH 需先读)。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        sidecar = (
            tmp_path / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song.ttml"
        )
        sidecar.unlink()
        rowid = await _insert_track(store, audio)

        resp = await client.patch(
            f"/api/lyrics/{rowid}/edit",
            json={
                "line_index": 0,
                "span_index": 0,
                "begin_ms": 1,
                "end_ms": 2,
            },
        )
        assert resp.status_code == 404

    async def test_patch_preserves_other_spans(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """PATCH 改一个 span 不影响其它 span/line(回归断言)。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        await client.patch(
            f"/api/lyrics/{rowid}/edit",
            json={
                "line_index": 0,
                "span_index": 0,
                "begin_ms": 100,
                "end_ms": 700,
            },
        )
        resp = await client.get(f"/api/lyrics/{rowid}/edit")
        doc = resp.json()
        # 改了的
        assert doc["lines"][0]["spans"][0] == {
            "text": "你",
            "begin_ms": 100,
            "end_ms": 700,
        }
        # 没改的
        assert doc["lines"][0]["spans"][1] == {
            "text": "好",
            "begin_ms": 800,
            "end_ms": 1600,
        }
        # 第二行没动
        assert doc["lines"][1]["text"] == "纯文本行"
        assert doc["lines"][1]["begin_ms"] == 5000


# ---------------------------------------------------------------------------
# editor_routes 测试 — POST
# ---------------------------------------------------------------------------


class TestPostRoute:
    """POST /api/lyrics/{track_id}/edit 全量替换测试。"""

    async def test_post_full_replace_creates_sidecar(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """POST 全量替换:sidecar 不存在时创建,存在时覆盖。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        # 删掉已有 sidecar,验证 POST 能创建
        sidecar = (
            tmp_path / ".lyrics" / "apple" / "Artist" / "Album" / "01 Song.ttml"
        )
        sidecar.unlink()
        rowid = await _insert_track(store, audio)

        new_doc = {
            "source": "apple",
            "lines": [
                {
                    "key": "N1",
                    "begin_ms": 100,
                    "end_ms": 1000,
                    "spans": [
                        {"text": "新", "begin_ms": 100, "end_ms": 500},
                    ],
                    "text": "",
                },
            ],
        }
        resp = await client.post(f"/api/lyrics/{rowid}/edit", json=new_doc)
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "apple"
        assert body["doc"]["lines"][0]["spans"][0]["text"] == "新"
        assert body["path"].endswith("01 Song.ttml")

        # 确认写盘(POST 创建了刚才删掉的 sidecar)
        assert sidecar.is_file()
        written = sidecar.read_text(encoding="utf-8")
        assert "新" in written
        assert "00:00:00.100" in written  # 100ms 格式化

    async def test_post_writes_to_source_path(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """POST body source=qq → 写入 .lyrics/qq/.../01 Song-qq.ttml(路径由 source 决定)。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        new_doc = {
            "source": "qq",
            "lines": [
                {
                    "key": "N1",
                    "begin_ms": 0,
                    "end_ms": 1000,
                    "spans": [],
                    "text": "qq 内容",
                },
            ],
        }
        resp = await client.post(f"/api/lyrics/{rowid}/edit", json=new_doc)
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "qq"
        # qq 路径带 -qq 后缀
        assert body["path"].endswith("01 Song-qq.ttml")
        assert ".lyrics" + "\\qq\\" in body["path"] or "/.lyrics/qq/" in body["path"]
        # 文件已写盘
        qq_sidecar = (
            tmp_path / ".lyrics" / "qq" / "Artist" / "Album" / "01 Song-qq.ttml"
        )
        assert qq_sidecar.is_file()

    async def test_post_overwrites_existing(
        self,
        store: IndexStore,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """POST 覆盖已有 sidecar(GET 读回等于 POST 的内容)。"""
        monkeypatch.setenv("LYRA_MUSIC_LIBRARY_ROOT", str(tmp_path))
        audio = _write_sidecar(tmp_path, "apple")
        rowid = await _insert_track(store, audio)

        new_doc = {
            "source": "apple",
            "lines": [
                {
                    "key": "X",
                    "begin_ms": 0,
                    "end_ms": 2000,
                    "spans": [],
                    "text": "全新内容",
                },
            ],
        }
        resp = await client.post(f"/api/lyrics/{rowid}/edit", json=new_doc)
        assert resp.status_code == 200

        get_resp = await client.get(f"/api/lyrics/{rowid}/edit")
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["lines"][0]["text"] == "全新内容"
        assert body["lines"][0]["spans"] == []

    async def test_post_invalid_track_id(self, client: AsyncClient) -> None:
        """非数字 track_id → 422。"""
        resp = await client.post(
            "/api/lyrics/abc/edit",
            json={"source": "apple", "lines": []},
        )
        assert resp.status_code == 422

    async def test_post_track_not_found(
        self,
        store: IndexStore,
        client: AsyncClient,
    ) -> None:
        """track 不存在 → 404。"""
        resp = await client.post(
            "/api/lyrics/999999/edit",
            json={"source": "apple", "lines": []},
        )
        assert resp.status_code == 404
