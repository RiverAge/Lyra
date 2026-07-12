# Lyra

自用的音乐元数据与歌词管理 Web 应用。部署在 TrueNAS 上，管理 Apple Music 解密库的元数据对照、标签补全、歌词甄选与逐字编辑。

## 状态

🚧 规划中 — 需求规格见 [docs/requirements.md](docs/requirements.md)

## 技术栈

- 后端：Go（单二进制）
- 前端：Vue3 + TS + Vite + Tailwind + pnpm
- 标签读写：[tunetag](https://github.com/cabbagekobe/tunetag)（纯 Go，原生支持 iTunes freeform atom）
- 文件监听：fsnotify
- 索引：SQLite
- 部署：Docker（TrueNAS，bind mount ZFS）

## 目录结构

```
Lyra/
├── docs/            # 需求规格与设计文档
├── frontend/        # Vue3 前端
├── cmd/lyra/        # Go 后端入口
├── internal/        # Go 业务逻辑
└── go.mod
```

## 范围

**做**：元数据浏览/对照/补全、歌词甄选/逐字编辑/留档、自建文件索引与检索、音频播放

**不做**：音频解密、Navidrome 管理、AI 声学分析
