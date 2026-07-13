"""Lyra 元数据写入/对比模块。

包含：
- writer.py：对磁盘文件就地写标签（MP4/FLAC/MP3）
- diff.py：before/after 对比纯函数

字段映射表（FIELD_MAP）在 writer.py 中定义，diff.py 导入复用，
确保两处映射互逆一致。
"""

from __future__ import annotations