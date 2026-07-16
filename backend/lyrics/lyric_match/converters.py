# ruff: noqa: UP009, UP031, E741, E501 - 逐字从 AppleMusicDecrypt tools/lyric_match 搬迁，
# XML 转义对齐 Go lyric-bridge（§3.9 行为等价，零改）；风格问题保留原码
# -*- coding: utf-8 -*-
"""NetEase /lyric/new (and QQ QRC) JSON → TTML conversion.

Pure functions, zero external dependencies (stdlib re / dataclasses only).
XML escaping mirrors Go xml.EscapeText so the output is byte-identical to the
lyric-bridge Go implementation for NetEase yrc/lrc sources.

QQ QRC is the same shape as NetEase yrc — `[line_start,line_dur](span_start,span_dur)text`
— except it has no third `(start,dur,type)` parameter. `_YRC_SPAN_RE` already
makes that third group optional, so `_parse_yrc` consumes QRC verbatim. The
QQ-specific entry point `qrc_xml_to_ttml` is added in stage 2 (QQ provider).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---- regex / constants ----
_YRC_LINE_RE = re.compile(r"^\s*\[(\d+),(\d+)\](.*)$")
_YRC_SPAN_RE = re.compile(r"\((\d+),(\d+)(?:,\d+)?\)")
_LRC_TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:\.\d{1,3})?)\]")
_ENHANCED_LRC_TIME_RE = re.compile(r"<\d{1,3}:\d{1,2}(?:\.\d{1,3})?>")
_SOURCE_XMLNS = "https://github.com/AppleMusicDecrypt/lyrics"


@dataclass
class _TtmlSpan:
    start: int
    end: int
    text: str


@dataclass
class _TtmlLine:
    key: str = ""
    start: int = 0
    end: int = 0
    text: str = ""
    spans: list = field(default_factory=list)


@dataclass
class _TimedText:
    start: int = 0
    end: int = 0
    text: str = ""


def _escape_text(value: str) -> str:
    # Go xml.EscapeText 转义集: & < > " ' \n \t \r
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


def _escape_attr(value: str) -> str:
    # Go: strings.ReplaceAll(escapeXMLText(value), `"`, "&quot;")
    # escapeXMLText 已把 " 转成 &#34;, 此处 ReplaceAll 对已无字面 " 的串是 no-op。
    return _escape_text(value).replace('"', "&quot;")


def _format_ttml_time(ms: int) -> str:
    if ms < 0:
        ms = 0
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    ms %= 60000
    seconds = ms // 1000
    millis = ms % 1000
    return "%02d:%02d:%02d.%03d" % (hours, minutes, seconds, millis)


def _must_atoi(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _split_lines(value: str) -> list:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value.split("\n")


def _parse_lrc_time(minute_part: str, second_part: str):
    try:
        minutes = int(minute_part)
    except ValueError:
        return None
    try:
        seconds = float(second_part)
    except ValueError:
        return None
    return int(round((minutes * 60 + seconds) * 1000))


def _is_lrc_metadata_line(text: str) -> bool:
    if text.startswith("[") and ":" in text:
        return True
    lower = text.strip().lower()
    for prefix in ("ar:", "al:", "ti:", "by:", "offset:"):
        if lower.startswith(prefix):
            return True
    return False


def _parse_yrc_spans(body: str, line_start: int, line_end: int) -> list:
    matches = list(_YRC_SPAN_RE.finditer(body))
    if len(matches) == 0:
        text = body.strip()
        if text == "":
            return []
        return [_TtmlSpan(start=line_start, end=line_end, text=text)]
    # 两种 yrc 形态：
    #   netease: body 以 `(` 开头 — `(...)`标记其【后】的字
    #            e.g. (21570,340,0)就(21910,260,0)要  → 「就」配 (21570,...)
    #   QQ QRC : body 以字开头   — `(...)`标记其【前】的字
    #            e.g. 张(0,6640)信(6640,6640)哲          → 「张」配 (0,...)
    # 用方向标志统一处理：netease 取「本次 ) 后→下次 ( 前」；
    # QQ 取「上次 ) 后→本次 ( 前」（首 span 取 body 开头→首个 ( 前）。
    qq_style = body[:1] != "("
    spans = []
    for i, m in enumerate(matches):
        start_text = body[m.start(1):m.end(1)]
        dur_text = body[m.start(2):m.end(2)]
        if qq_style:
            # `(...)` 标记其前的字：上个 ) 后（首 span 为 body 开头）到本次 ( 前
            text_start = matches[i - 1].end() if i > 0 else 0
            text_end = m.start()
        else:
            # netease：`(...)` 标记其后的字：本次 ) 后到下次 ( 前
            text_start = m.end()
            text_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[text_start:text_end]
        if text == "":
            continue
        start = _must_atoi(start_text)
        duration = _must_atoi(dur_text)
        if start < line_start and line_start + start <= line_end + 500:
            start += line_start
        spans.append(_TtmlSpan(start=start, end=start + duration, text=text))
    return spans


def _join_span_text(spans: list) -> str:
    return "".join(span.text for span in spans)


def _parse_yrc(raw: str) -> list:
    lines = []
    for raw_line in _split_lines(raw):
        m = _YRC_LINE_RE.match(raw_line)
        if not m:
            continue
        start = _must_atoi(m.group(1))
        duration = _must_atoi(m.group(2))
        end = start + duration
        body = m.group(3)
        spans = _parse_yrc_spans(body, start, end)
        text = _join_span_text(spans)
        if text.strip() == "":
            continue
        for span in spans:
            if span.end > end:
                end = span.end
        lines.append(_TtmlLine(start=start, end=end, text=text, spans=spans))
    lines.sort(key=lambda l: l.start)
    return lines


def _parse_lrc(raw: str) -> list:
    lines = []
    for raw_line in _split_lines(raw):
        matches = _LRC_TIMESTAMP_RE.findall(raw_line)
        if len(matches) == 0:
            continue
        text = _LRC_TIMESTAMP_RE.sub("", raw_line)
        text = _ENHANCED_LRC_TIME_RE.sub("", text)
        text = text.strip()
        if text == "" or _is_lrc_metadata_line(text):
            continue
        for mm, ss in matches:
            start = _parse_lrc_time(mm, ss)
            if start is None:
                continue
            lines.append(_TimedText(start=start, text=text))
    lines.sort(key=lambda t: t.start)
    for i in range(len(lines)):
        end = lines[i].start + 4000
        if i + 1 < len(lines) and lines[i + 1].start > lines[i].start:
            end = lines[i + 1].start
        lines[i].end = end
    return lines


def _lrc_to_main_lines(items: list) -> list:
    return [_TtmlLine(start=it.start, end=it.end, text=it.text) for it in items]


def _lrc_to_aux_lines(items: list) -> list:
    """lrc 逐行 _TimedText → _TtmlLine（spans=[]，逐行 track 用）。

    netease 翻译(tlyric)/注音(romalrc) 是 lrc 形态逐行，包成 _TtmlLine 走
    和主歌词同一套 div track 写法（无 spans = 纯文本 <p>）。
    """
    return [_TtmlLine(start=it.start, end=it.end, text=it.text, spans=[]) for it in items]


def _assign_line_keys(lines: list) -> None:
    for i, line in enumerate(lines):
        if line.key == "":
            line.key = "L%d" % (i + 1)


def _match_to_main_lines(main: list, aux: list) -> list:
    """把 aux（翻译/注音行，_TtmlLine[]）按 start 匹配 main 行的 key。

    aux 行无 key（_parse_yrc/_lrc_to_aux_lines 不赋 key）；按 aux.start 最接近
    哪个 main.start，就继承那个 main 行的 key + 时间区间。未匹配上的丢弃
    （翻译/注音行数可能与 main 不完全对齐，按时间就近配对，与旧 _match_metadata_lines
    同语义）。返回带 key 的新 _TtmlLine[]（保留 aux 的 spans/text：逐字 aux 保留 spans，
    逐行 aux spans=[]）。
    """
    if len(main) == 0 or len(aux) == 0:
        return []
    out: list = []
    if len(aux) == len(main):
        # 行数相等：按下标一一配对（翻译/注音行与主歌词行通常严格对齐）
        for i, line in enumerate(main):
            src = aux[i]
            if src.text.strip() == "":
                continue
            out.append(_TtmlLine(
                key=line.key,
                start=src.start,
                end=src.end if src.end else line.end,
                text=src.text,
                spans=list(src.spans),
            ))
        return out
    # 行数不等：按 start 时间就近配对（每个 aux 找最近 main，已用过的 aux 不重用）
    used = [False] * len(aux)
    for line in main:
        best = -1
        best_delta = 1501
        for j, item in enumerate(aux):
            if used[j] or item.text.strip() == "":
                continue
            delta = abs(item.start - line.start)
            if delta < best_delta:
                best = j
                best_delta = delta
        if best == -1:
            continue
        used[best] = True
        src = aux[best]
        out.append(_TtmlLine(
            key=line.key,
            start=src.start,
            end=src.end if src.end else line.end,
            text=src.text,
            spans=list(src.spans),
        ))
    return out


def _parse_qrc_aux(qrc_xml: str) -> list:
    """QQ contentts/contentroma 解密 XML → _TtmlLine[]（带逐字 spans）。

    抽 LyricContent → _parse_yrc（QRC 形态，逐字 span）。供 QQ 翻译/注音复用。
    无 LyricContent / 无行 → 返回 []。
    """
    main_raw = _extract_qrc_lyric_content(qrc_xml).strip()
    if not main_raw:
        return []
    return _parse_yrc(main_raw)


def _write_div_track(b: list, role: str, lang: str, lines: list) -> None:
    """在 <body> 下写一个 <div role=... xml:lang=...> track。

    每行 _TtmlLine：有 spans → 逐字 <p key begin end><span begin end>字</span>...</p>；
    无 spans → 纯文本 <p key begin end>文本</p>。和主歌词 div 同一写法。
    空列表不写 div（无该 track）。
    """
    if not lines:
        return
    b.append('    <div role="')
    b.append(role)
    b.append('" xml:lang="')
    b.append(_escape_attr(lang))
    b.append('">\n')
    for line in lines:
        b.append("      ")
        b.append('<p key="')
        b.append(_escape_attr(line.key))
        b.append('" begin="')
        b.append(_format_ttml_time(line.start))
        b.append('" end="')
        b.append(_format_ttml_time(line.end))
        b.append('">')
        if len(line.spans) == 0:
            b.append(_escape_text(line.text))
        else:
            for span in line.spans:
                b.append('<span begin="')
                b.append(_format_ttml_time(span.start))
                b.append('" end="')
                b.append(_format_ttml_time(span.end))
                b.append('">')
                b.append(_escape_text(span.text))
                b.append("</span>")
        b.append("</p>\n")
    b.append("    </div>\n")


def _build_ttml(
    source: str,
    main: list,
    translations: list,
    pronunciations: list,
    main_lang: str = "und",
) -> str:
    """生成多 div track TTML（遵循 TTML 协议）。

    <body> 下按 role 写多个 <div> track：
      - role="main" xml:lang=main_lang：主歌词（逐字 span 或逐行纯文本）
      - role="translation" xml:lang="zh-Hans"：翻译（逐行/逐字，translations _TtmlLine[]）
      - role="transliteration" xml:lang="und-Latn"：注音/罗马音（逐字/逐行）
    translations/pronunciations 为带 key 的 _TtmlLine[]（调用方经 _match_to_main_lines
    匹配过 main 行 key）；空列表不出 div。
    """
    b = []
    b.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    b.append('<tt xmlns="http://www.w3.org/ns/ttml" xmlns:amdl="' + _SOURCE_XMLNS + '" xml:lang="und">\n')
    b.append("  <head>\n")
    b.append("    <metadata>\n")
    b.append("      <amdl:source>" + _escape_text(source) + "</amdl:source>\n")
    b.append("    </metadata>\n")
    b.append("  </head>\n")
    b.append('  <body xml:lang="und">\n')
    _write_div_track(b, "main", main_lang, main)
    _write_div_track(b, "translation", "zh-Hans", translations)
    _write_div_track(b, "transliteration", "und-Latn", pronunciations)
    b.append("  </body>\n")
    b.append("</tt>\n")
    return "".join(b)


def _unwrap_payload(data: dict) -> dict:
    payload = data
    for key in ("payload", "lyrics_payload", "raw"):
        if key in data:
            nested = data[key]
            if nested is not None:
                payload = nested
                break
    return payload


def _lyric_str(block) -> str:
    if isinstance(block, dict):
        return str(block.get("lyric") or "")
    return ""


def payload_to_ttml(payload: dict, source: str = "netease") -> str:
    """NetEase /lyric/new payload dict → TTML 字符串。

    yrc.lyric 与 lrc.lyric 都空时 raise ValueError。
    """
    p = _unwrap_payload(payload)
    yrc_lyric = _lyric_str(p.get("yrc")).strip()
    lrc_lyric = _lyric_str(p.get("lrc")).strip()

    main = []
    if yrc_lyric != "":
        main = _parse_yrc(yrc_lyric)
    if len(main) == 0 and lrc_lyric != "":
        main = _lrc_to_main_lines(_parse_lrc(lrc_lyric))
    if len(main) == 0:
        raise ValueError("no supported NetEase lyric text")

    _assign_line_keys(main)
    # netease 翻译(tlyric)/注音(romalrc) 是 lrc 形态逐行 → _TtmlLine(spans=[])，
    # 经 _match_to_main_lines 按 start 匹配 main 行 key，产出带 key 的逐行 track。
    translations = _match_to_main_lines(
        main, _lrc_to_aux_lines(_parse_lrc(_lyric_str(p.get("tlyric"))))
    )
    pronunciations = _match_to_main_lines(
        main, _lrc_to_aux_lines(_parse_lrc(_lyric_str(p.get("romalrc"))))
    )
    return _build_ttml(source, main, translations, pronunciations)


# ---- QQ QRC XML → TTML ----

# QRC XML carries the lyric inside `LyricContent="..."` attributes, e.g.:
#   <QrcInfos><LyricInfo LyricCount="1"><Lyric_1 LyricType="1" LyricContent="[ti:..]\n[ar:..]\n[0,1000](0,500)字...">
# The LyricContent value is the same yrc shape NetEase uses ([line_start,line_dur](span_start,span_dur)text),
# prefixed by [ti:]/[ar:]/[al:]/[offset:] LRC-style metadata lines that _parse_yrc already skips
# (they do not match _YRC_LINE_RE). No third (type) param — _YRC_SPAN_RE makes it optional.
_QRC_LYRIC_CONTENT_RE = re.compile(r'LyricContent="([^"]*)"')


def _extract_qrc_lyric_content(qrc_xml: str) -> str:
    """Pull the LyricContent value out of a decrypted QRC XML string.

    The XML attributes use double-quote quoting and the value itself never
    contains a raw `"` (lyric text does not), so a non-greedy `[^"]*` capture is
    safe and avoids pulling in a real XML parser. Returns "" if absent
    (e.g. an empty translation/roma payload).
    """
    m = _QRC_LYRIC_CONTENT_RE.search(qrc_xml)
    return m.group(1) if m else ""


def qrc_xml_to_ttml(payload: dict, source: str = "qq") -> str:
    """QQ payload（含 _qrc_xml 主 + _qrc_ts_xml 翻译 + _qrc_roma_xml 注音）→ 多 div track TTML。

    主歌词走 _parse_yrc（逐字 span）；翻译(contentts)/注音(contentroma) 是独立加密
    payload，provider 解密成 QRC XML 后存 _qrc_ts_xml/_qrc_roma_xml，这里经
    _parse_qrc_aux 解析成逐字 _TtmlLine[]，再 _match_to_main_lines 匹配 main 行 key。
    空 aux（无翻译/注音）→ []，不出对应 div。主 LyricContent 空 → ValueError。
    """
    qrc_xml = str(payload.get("_qrc_xml") or "")
    main_raw = _extract_qrc_lyric_content(qrc_xml).strip()
    if not main_raw:
        raise ValueError("no QRC LyricContent in decrypted XML")
    main = _parse_yrc(main_raw)
    if not main:
        raise ValueError("QRC LyricContent parsed to no lines")
    _assign_line_keys(main)
    # QQ 翻译(contentts)/注音(contentroma)：QRC 形态逐字 → _TtmlLine[] 带 spans，
    # 按 start 匹配 main 行 key。空/缺 → []。
    translations = _match_to_main_lines(main, _parse_qrc_aux(str(payload.get("_qrc_ts_xml") or "")))
    pronunciations = _match_to_main_lines(main, _parse_qrc_aux(str(payload.get("_qrc_roma_xml") or "")))
    return _build_ttml(source, main, translations, pronunciations)


# Backward-compat alias for any call site still using the old name.
netease_payload_to_ttml = payload_to_ttml
