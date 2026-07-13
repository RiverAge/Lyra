"""逐字歌词编辑器:TTML XML ↔ span 数据结构。

实现 TTML sidecar 的解析/序列化与逐字编辑(改 span/line 的 begin/end)。

格式契约来源:`AppleMusicDecrypt-Windows/tools/lyric_match/converters.py` 的
`_build_ttml` / `_format_ttml_time` / `_escape_text`。本模块照搬这三个函数的
逻辑(时间格式 HH:MM:SS.mmm、Go xml.EscapeText 转义集、tt/head/metadata/body/div
骨架),保证 parse → serialize round-trip 不丢信息(审计规则 §3.9),且编辑后写回
不产生时间格式漂移。

数据结构(对齐 converters.py 的 _TtmlSpan/_TtmlLine,用公开命名):
- Span: text + begin_ms + end_ms
- Line: key + begin_ms + end_ms + spans 列表(空列表 = 纯文本行)
- LyricDoc: lines 列表 + source(amdl:source 值)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from xml.etree import ElementTree as ET

# TTML 命名空间常量(对齐 converters.py)
_TTML_NS = "http://www.w3.org/ns/ttml"
_AMDL_NS = "https://github.com/AppleMusicDecrypt/lyrics"
# ElementTree 带命名空间的 tag 形如 "{ns}local"
_TT = f"{{{_TTML_NS}}}tt"
_HEAD = f"{{{_TTML_NS}}}head"
_METADATA = f"{{{_TTML_NS}}}metadata"
_BODY = f"{{{_TTML_NS}}}body"
_DIV = f"{{{_TTML_NS}}}div"
_P = f"{{{_TTML_NS}}}p"
_SPAN = f"{{{_TTML_NS}}}span"
_AMDL_SOURCE = f"{{{_AMDL_NS}}}source"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_KEY = "key"
_BEGIN = "begin"
_END = "end"

# 时间格式:HH:MM:SS.mmm(对齐 converters._format_ttml_time,含小时,负数→0)
_TIME_RE = re.compile(
    r"^(?P<h>\d{1,3}):(?P<m>\d{1,2}):(?P<s>\d{1,2})(?:\.(?P<ms>\d{1,3}))?$",
)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Span:
    """逐字 span:文本 + begin/end 毫秒。"""

    text: str
    begin_ms: int
    end_ms: int


@dataclass
class Line:
    """歌词行:key + begin/end 毫秒 + spans 列表。

    spans 为空表示纯文本行(<p>纯文本</p>,无逐字时间)。
    text 字段为纯文本行的内容;有 spans 时 text 不参与序列化(spans 自带文本)。
    """

    key: str
    begin_ms: int
    end_ms: int
    spans: list[Span] = field(default_factory=list)
    text: str = ""


@dataclass
class LyricDoc:
    """整份歌词文档:lines 列表 + source(amdl:source 值)。"""

    lines: list[Line] = field(default_factory=list)
    source: str = "netease"


# ---------------------------------------------------------------------------
# 时间格式化/解析(照搬 converters._format_ttml_time 逻辑,保证格式一致)
# ---------------------------------------------------------------------------


def format_ttml_time(ms: int) -> str:
    """毫秒 → HH:MM:SS.mmm(与 converters._format_ttml_time 字节一致)。

    负数归零,毫秒部分补零到 3 位。
    """
    if ms < 0:
        ms = 0
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def parse_ttml_time(value: str) -> int:
    """HH:MM:SS.mmm → 毫秒(format_ttml_time 的逆运算)。

    支持可选毫秒部分。无法解析返回 0(宽容输入,不抛——避免单个坏时间戳
    导致整份文档不可读)。
    """
    m = _TIME_RE.match(value.strip())
    if m is None:
        return 0
    hours = int(m.group("h"))
    minutes = int(m.group("m"))
    seconds = int(m.group("s"))
    ms_str = m.group("ms")
    millis = int(ms_str) if ms_str is not None else 0
    return hours * 3600000 + minutes * 60000 + seconds * 1000 + millis


# ---------------------------------------------------------------------------
# XML 转义(照搬 converters._escape_text/_escape_attr,Go xml.EscapeText 对齐)
# ---------------------------------------------------------------------------


def escape_text(value: str) -> str:
    """转义文本节点(对齐 Go xml.EscapeText)。

    converters._escape_text 原样搬:&,<,>,",' 换行/制表/回车。
    """
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&#34;")
        .replace("'", "&#39;")
        .replace("\n", "&#xA;")
        .replace("\t", "&#x9;")
        .replace("\r", "&#xD;")
    )


def escape_attr(value: str) -> str:
    """转义属性值(对齐 converters._escape_attr)。

    escape_text 后再把字面 " 替成 &quot;(escape_text 已无字面 ",此为 no-op)。
    """
    return escape_text(value).replace('"', "&quot;")


# ---------------------------------------------------------------------------
# parse:TTML XML → LyricDoc(命名空间感知)
# ---------------------------------------------------------------------------


def _strip_tags_and_tail(elem: ET.Element) -> str:
    """提取元素的纯文本内容(span 子元素被展平为其 text+tail)。

    对 <p>纯文本</p>(无 span)取 .text;
    对 <p><span>字</span><span>字</span></p> 取各 span 的 text+tail 拼接
    (tail 是 span 之间/之后的裸文本)。
    """
    parts: list[str] = []
    if elem.text is not None:
        parts.append(elem.text)
    for child in elem:
        if child.text is not None:
            parts.append(child.text)
        if child.tail is not None:
            parts.append(child.tail)
    return "".join(parts)


def parse_ttml(xml_text: str) -> LyricDoc:
    """TTML XML 字符串 → LyricDoc。

    命名空间感知(用 ET 而非正则,正确处理 ns 重定义)。读取:
    - head/metadata/amdl:source → doc.source
    - body/div/p[key/begin/end] → Line
      - p 含 span → Line.spans(每 span 的 begin/end/text)
      - p 无 span → Line.text(p 的纯文本),spans 为空
    """
    # wrap 进 try:bad XML → ValueError
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"Invalid TTML XML: {e}") from e

    source = _read_source(root)
    lines = _read_lines(root)
    return LyricDoc(lines=lines, source=source)


def _read_source(root: ET.Element) -> str:
    """读 head/metadata/amdl:source 文本。缺失返回默认 'netease'。"""
    source = "netease"
    head = root.find(_HEAD)
    if head is not None:
        metadata = head.find(_METADATA)
        if metadata is not None:
            amdl_source = metadata.find(_AMDL_SOURCE)
            if amdl_source is not None and amdl_source.text is not None:
                source = amdl_source.text
    return source


def _read_lines(root: ET.Element) -> list[Line]:
    """读 body/div/p 列表 → Line 列表。"""
    lines: list[Line] = []
    body = root.find(_BODY)
    if body is None:
        return lines
    div = body.find(_DIV)
    if div is None:
        return lines
    for p in div.findall(_P):
        key = p.get(_KEY, "")
        begin_ms = parse_ttml_time(p.get(_BEGIN, ""))
        end_ms = parse_ttml_time(p.get(_END, ""))
        spans = _read_spans(p)
        if spans:
            lines.append(Line(key=key, begin_ms=begin_ms, end_ms=end_ms, spans=spans))
        else:
            text = _strip_tags_and_tail(p)
            lines.append(
                Line(key=key, begin_ms=begin_ms, end_ms=end_ms, text=text),
            )
    return lines


def _read_spans(p: ET.Element) -> list[Span]:
    """读 p 下的 span 列表 → Span 列表。无 span 返回空。"""
    spans: list[Span] = []
    for sp in p.findall(_SPAN):
        text = sp.text if sp.text is not None else ""
        # span 内不应再嵌套 span,但若出现则展平(防御性)
        if sp.text is None and len(sp) > 0:
            text = _strip_tags_and_tail(sp)
        spans.append(
            Span(
                text=text,
                begin_ms=parse_ttml_time(sp.get(_BEGIN, "")),
                end_ms=parse_ttml_time(sp.get(_END, "")),
            ),
        )
    return spans


# ---------------------------------------------------------------------------
# serialize:LyricDoc → TTML XML(格式对齐 converters._build_ttml)
# ---------------------------------------------------------------------------


def serialize_ttml(doc: LyricDoc) -> str:
    """LyricDoc → TTML XML 字符串(格式对齐 converters._build_ttml)。

    骨架:xml 头 / tt(ns+amdl+xml:lang=und) / head>metadata>amdl:source /
    body(xml:lang=und)>div>p[span|文本]。

    p 无 spans 时输出纯文本,有 spans 时输出 span 序列——与 _build_ttml 分支一致。
    """
    b: list[str] = []
    b.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    b.append(
        '<tt xmlns="' + _TTML_NS + '" xmlns:amdl="' + _AMDL_NS + '" xml:lang="und">\n',
    )
    b.append("  <head>\n")
    b.append("    <metadata>\n")
    b.append("      <amdl:source>" + escape_text(doc.source) + "</amdl:source>\n")
    b.append("    </metadata>\n")
    b.append("  </head>\n")
    b.append('  <body xml:lang="und">\n')
    b.append("    <div>\n")
    for line in doc.lines:
        b.append("      ")
        b.append('<p key="')
        b.append(escape_attr(line.key))
        b.append('" begin="')
        b.append(format_ttml_time(line.begin_ms))
        b.append('" end="')
        b.append(format_ttml_time(line.end_ms))
        b.append('">')
        if line.spans:
            for span in line.spans:
                b.append('<span begin="')
                b.append(format_ttml_time(span.begin_ms))
                b.append('" end="')
                b.append(format_ttml_time(span.end_ms))
                b.append('">')
                b.append(escape_text(span.text))
                b.append("</span>")
        else:
            b.append(escape_text(line.text))
        b.append("</p>\n")
    b.append("    </div>\n")
    b.append("  </body>\n")
    b.append("</tt>\n")
    return "".join(b)


# ---------------------------------------------------------------------------
# 编辑操作(返回更新后的 doc,不可变语义——返回新对象)
# ---------------------------------------------------------------------------


def update_span_time(
    doc: LyricDoc,
    line_index: int,
    span_index: int,
    begin_ms: int,
    end_ms: int,
) -> LyricDoc:
    """更新指定 span 的 begin/end,返回新 doc(不修改原 doc)。

    Args:
        doc: 原文档
        line_index: 行索引(0-based)
        span_index: 该行内 span 索引(0-based)
        begin_ms: 新 begin 毫秒
        end_ms: 新 end 毫秒

    Raises:
        IndexError: line_index 或 span_index 越界
    """
    if line_index < 0 or line_index >= len(doc.lines):
        raise IndexError(f"line_index {line_index} out of range (0..{len(doc.lines) - 1})")
    new_lines = list(doc.lines)
    old_line = new_lines[line_index]
    if span_index < 0 or span_index >= len(old_line.spans):
        raise IndexError(
            f"span_index {span_index} out of range (0..{len(old_line.spans) - 1})",
        )
    new_spans = list(old_line.spans)
    new_spans[span_index] = replace(
        new_spans[span_index],
        begin_ms=begin_ms,
        end_ms=end_ms,
    )
    new_lines[line_index] = replace(old_line, spans=new_spans)
    return replace(doc, lines=new_lines)


def update_line_time(
    doc: LyricDoc,
    line_index: int,
    begin_ms: int,
    end_ms: int,
) -> LyricDoc:
    """更新指定 line 的 begin/end,返回新 doc(不修改原 doc)。

    Args:
        doc: 原文档
        line_index: 行索引(0-based)
        begin_ms: 新 begin 毫秒
        end_ms: 新 end 毫秒

    Raises:
        IndexError: line_index 越界
    """
    if line_index < 0 or line_index >= len(doc.lines):
        raise IndexError(f"line_index {line_index} out of range (0..{len(doc.lines) - 1})")
    new_lines = list(doc.lines)
    new_lines[line_index] = replace(
        new_lines[line_index],
        begin_ms=begin_ms,
        end_ms=end_ms,
    )
    return replace(doc, lines=new_lines)


# ---------------------------------------------------------------------------
# 文档深度相等(供 round-trip 测试断言)
# ---------------------------------------------------------------------------


def docs_equal(a: LyricDoc, b: LyricDoc) -> bool:
    """两份 LyricDoc 是否深度相等(source + lines 全匹配)。"""
    if a.source != b.source:
        return False
    if len(a.lines) != len(b.lines):
        return False
    for la, lb in zip(a.lines, b.lines, strict=True):
        if not _lines_equal(la, lb):
            return False
    return True


def _lines_equal(a: Line, b: Line) -> bool:
    if a.key != b.key or a.begin_ms != b.begin_ms or a.end_ms != b.end_ms:
        return False
    if a.text != b.text:
        return False
    if len(a.spans) != len(b.spans):
        return False
    for sa, sb in zip(a.spans, b.spans, strict=True):
        if sa.text != sb.text or sa.begin_ms != sb.begin_ms or sa.end_ms != sb.end_ms:
            return False
    return True
