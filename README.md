# Lyra

自用的音乐元数据与歌词管理 Web 应用。部署在 TrueNAS 上，管理 Apple Music 解密库的元数据对照、标签补全、歌词甄选与逐字编辑。

## 状态

🚧 规划中 — 需求规格见 [docs/requirements.md](docs/requirements.md)

## 技术栈

- 后端：Python + FastAPI（uvicorn）
- 前端：Vue3 + TS + Vite + Tailwind + pnpm
- 标签读写：[mutagen](https://github.com/quodlibet/mutagen)（生产级，通吃 m4a/flac/mp3 全格式）
- 文件监听：[watchdog](https://github.com/gorakhargosh/watchdog)（debounce，参照 Navidrome `WatcherWait=5s`）
- 索引：SQLite
- 迁移：Alembic
- 部署：Docker（TrueNAS，bind mount ZFS）

## 目录结构

```
Lyra/
├── docs/            # 需求规格与设计文档
├── frontend/        # Vue3 前端
├── backend/         # FastAPI 后端
├── scripts/         # quality-gate 等工程脚本
└── .husky/          # git hooks（pre-commit / pre-push）
```

## 范围

**做**：元数据浏览/对照/补全、歌词甄选/逐字编辑/留档、自建文件索引与检索、音频播放

**不做**：音频解密、Navidrome 管理、AI 声学分析
