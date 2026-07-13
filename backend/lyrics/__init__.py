"""Lyra 歌词层。

包含三块（M5-A/B/C 合流）：
- lyric_match/：在线歌词匹配（网易 weapi + QQ QRC），改壳自 AppleMusicDecrypt
- sidecar.py：.lyrics/ 目录下 TTML/JSON sidecar 读写 + 路径算法
- editor.py：逐字歌词编辑器（TTML XML ↔ span 数据结构）
"""
