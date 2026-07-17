# Lyra 需求规格

> 状态：基线（v0.1）——讨论收敛后的第一版固化。后续规格与开发以此为准。
> 维护者：需求方 + QA 共同维护。本文档描述「是什么/为什么」，不描述「怎么实现」。

---

## 1. 背景与目标

### 1.1 真实问题

音源库托管在 Navidrome（`music.587626.xyz`），大部分歌曲来自 Apple Music 解密下载，文件内带完整 Apple 元数据。当前痛点：

1. **没有统一的可视化界面**来看每首歌的完整元数据、判断哪些字段缺失或不一致。
2. **歌词供应链已成型但无管理入口**：Apple TTML / 网易 / QQ 三源 sidecar 已落地，在线匹配+甄选逻辑（`lyric_match`）已成型，但没有 Web 触发与甄选 UI。
3. **Apple 元数据对标无工具**：无法对照 Apple 权威值，发现本地标签缺失/不一致并补全。
4. **逐字歌词缺位**：Apple 仅有逐行歌词时，无便捷入口去补逐字歌词；自动匹配的歌词时间轴对不上时无调整手段。

### 1.2 项目定位

Lyra 是一个**自用的、部署在 TrueNAS 上的音乐元数据与歌词管理 Web 应用**。本质是已成型歌词供应链与元数据补全能力的**管理控制台 + UI**，不是一套新数据系统。

核心价值：在浏览器里完成「浏览/检索 → 元数据对照 → 标签补全 → 歌词甄选/编辑 → 留档」全链路。

### 1.3 非目标（明确不做）

- 不做音频解密（pywidevine / wrapper-manager / m3u8 封装均属 AppleMusicDecrypt 下载器职责）
- 不做 Navidrome 的 rescan 触发或配置管理（写完标签后 Navidrome 何时反映，不在本项目范围）
- 不做 AI 声学分析/聚类/智能歌单（那是邻居项目 AudioMuse-AI 的领域）
- 不做公开多用户服务（自用，单用户，挂内网域名）

---

## 2. 现状资产盘点

Lyra 站在已有资产前面加一层壳。重写时以这些 Python 资产为「参考翻译源」，不直接 import。

### 2.1 音频库结构

音频库的**逻辑结构**（相对路径，与物理挂载点无关）：

```
<音乐库根>/apple/Artist/Album/01 Song.m4a   ← Apple Music 解密下载产物
<音乐库根>/.lyrics/{apple,netease,qq}/...   ← 歌词 sidecar（见 §2.2）
```

物理挂载点是**部署配置**（见 §3），容器化后由 bind mount 决定：
- TrueNAS 容器内：本地路径（如 `/music`）
- Windows 操作端：SMB 盘符（如 `Y:\music`）

需求文档只描述逻辑结构 `<音乐库根>/...`，不写死任何物理路径。应用通过单一配置项读取挂载根。`apple/` 这一层是 Apple Music 解密下载器的目录约定，Lyra 作为消费者沿用。

> 当前环境示例：Windows 侧 SMB 盘符为 `Y:\music`，TrueNAS 上对应本地路径如 `/mnt/tank/music`，容器内 bind mount 如 `/music`。这些均为部署时配置，非需求约束。

### 2.2 歌词 sidecar 体系（已成型）

逻辑结构（`<音乐库根>` 下）：

```
<音乐库根>/.lyrics/apple/Artist/Album/01 Song.ttml         ← Apple 原始 TTML（默认主歌词，无后缀）
<音乐库根>/.lyrics/apple/Artist/Album/01 Song-netease.ttml ← 网易逐字增强（-netease 后缀）
<音乐库根>/.lyrics/apple/Artist/Album/01 Song.json         ← 网易原始歌词 JSON（同目录）
<音乐库根>/.lyrics/apple/Artist/Album/01 Song-qq.ttml      ← QQ QRC 逐字（-qq 后缀）
```

所有来源平铺在 `.lyrics/apple/` 下（音频镜像目录，保留 `apple/` 首段），靠文件名后缀区分——这是 navidrome lyric-bridge 的扫描契约（bridge 只在该目录扫 `song.ttml`/`song-netease.ttml`/`song-qq.ttml`）。sidecar 与音频同构镜像 `<音乐库根>/apple` 下相对路径。设计哲学见 `AppleMusicDecrypt-Windows/docs/lyrics-workflow.md`。

### 2.3 lyric_match（在线匹配，已成型）

位于 `AppleMusicDecrypt-Windows/tools/lyric_match/`，模块化：
- 双 provider：网易（weapi 加密）+ QQ（triple-DES QRC 解密）
- 统一打分（`AUTO_ACCEPT_SCORE=86` / `REVIEW_SCORE=74` / `MIN_ACCEPT_GAP=6`）
- TTML 转换器（`converters.py`，纯函数，零外部依赖）
- 批量目录扫描 + JSONL 输出 + sidecar 落盘
- **自包含**：把自己当顶层包 `lyric_match`，不依赖 `src.*`；第三方依赖仅 `pycryptodome`/`requests`/`beautifulsoup4`

### 2.4 lyric-bridge 插件（已成型，Navidrome 侧）

Go WASM 插件（`navidrome-plugins/lyric-bridge/`），运行时给 Navidrome 喂 sidecar 歌词，支持 `preferWordSynced`（逐字优先）+ 时间线兼容性校验。**不在 Lyra 范围**，但 Lyra 落盘的 sidecar 靠它消费。

### 2.5 Apple 元数据获取能力（已成型，复用思路明确）

两条互补路径，均**无需 Apple 会员账号/授权**：

**路径 A — Apple Music API（匿名 Bearer token）**
- 来源：参考 `AppleMusicDecrypt-Windows/src/api.py` 的 `WebAPI`
- 鉴权：`amp-api.music.apple.com` 要求 `Authorization: Bearer <jwt>`（已实证：无 token 或假 token → 401）。token 不是会员账号登录态，是 Apple Music 网页前端用的匿名 JWT
- 会员过期/无会员**不影响元数据查询**：元数据查询走 amp-api + 匿名 token，与"播放/下载加密音频"所需的会员态是两回事
- 能拿到的字段（`get_song_info` → `SongData.Attributes`）：name/artistName/albumName/trackNumber/discNumber/durationInMillis/releaseDate/isrc/composerName/genreNames/contentRating/explicit/hasLyrics/hasTimeSyncedLyrics/hasCredits/artwork(尺寸+主色)/audioTraits/audioLocale/url 等——**结构化、完整、权威**
- token 获取路径（已实证有效）：抓 `music.apple.com` 首页 → 正则 `/assets/index~[^/]+\.js` 命中首页 `<script type="module" src=...>` 引用 → 抓该 JS → 正则 `eyJ[A-Za-z0-9-_=]+\.\.\.` 抠出 JWT。下载器当前正常使用，此路径有效

**路径 B — credits 网页爬取**
- 来源：参考 `AppleMusicDecrypt-Windows/src/credits.py`
- 鉴权：无，匿名爬 `music.apple.com/{region}/song/{song_id}` 网页，解析 `<script id="serialized-server-data">` JSON
- 代理：`am.587626.xyz`（CF Worker，规避 IP 重定向）
- 能拿到：制作人员（composer/lyricist/producer/mixer/engineer/arranger/conductor/djmixer/performer），按 `data/role_map.toml` 映射
- region fallback：primary 区失败 → 并行探 us/jp/gb/kr/...，命中即返回
- 永久无 credits 哨兵：区分「临时失败」与「Apple 未录入」

**分工**：元数据对照走路径 A（结构化、权威）；制作人员 credits 走路径 B（API 的 `get_song_info` 只有 `hasCredits` 布尔，无明细）。

> **实证记录（2026-07-12）**：① amp-api 接口可达，无 token/假 token → 401，鉴权确认；② 首页 `<script type="module" src="/assets/index~8eb1313596.js">` 命中 `api.py` 正则；③ 该 JS 内含 `eyJ` JWT 特征 + `Bearer` + `amp-api` 引用；④ `api.py:_set_token` 路径当前有效，下载器正常使用合理。核心结论"匿名 token、无需会员"成立。

### 2.6 写标签能力（已成型）

`credits.py` 用 **mutagen** 写 m4a：
- 标准 key：`©wrt`（composer）等
- iTunes freeform：`----:com.apple.iTunes:{lyricist/producer/mixer/engineer/...}`
- 含 freeform 规范化、多值处理、去重

Lyra 直接复用 mutagen（见 §5），无替代库。

---

## 3. 部署拓扑

```
┌──────────────────────────────────────────────────────┐
│ TrueNAS (ZFS 池, 本地路径如 /mnt/tank/music)         │
│                                                      │
│  ┌─────────────┐        ┌──────────────────────┐     │
│  │ Navidrome   │        │ Lyra 容器 (Python)   │     │
│  │ 容器        │        │ 前端 Vue3 + FastAPI  │     │
│  │ -v <挂载点>←┤        ├── <挂载点> ←─────────┤     │
│  │  本地 bind  │        │  本地 bind mount(读写)│     │
│  └─────────────┘        └──────────────────────┘     │
│       ↑ 都看本地 ZFS 路径, inotify 可穿透            │
└──────────────────────────────────────────────────────┘
            ↑ SMB 仅作 Windows 访问通道 ↑
┌──────────────────────────────────────────────────────┐
│ Windows (操作端)                                      │
│  <盘符>:\music ← SMB 映射, 在这增删改/下载歌曲        │
│  + 跑 AppleMusicDecrypt 下载器 (start.bat)           │
└──────────────────────────────────────────────────────┘
```

要点：
- Lyra 容器与 Navidrome **同处境**——都是 TrueNAS Docker、bind mount 同一 ZFS 数据集
- 容器内的挂载点路径由部署配置决定（如 `/music`），应用通过单一配置项读取，不写死
- Windows 侧 SMB 盘符（如 `Y:\`）只是操作端的访问视角，与容器无关
- inotify/watchdog 对 ZFS **可穿透**，文件监听可用（和 Navidrome 同理）
- Windows 通过 SMB 改文件 → ZFS 层触发事件 → 容器能收到（SMB 是 Windows 侧访问协议，不影响 TrueNAS 本地事件）

---

## 4. 系统边界与数据流

### 4.1 系统边界图

```
┌──────────────────────────────────────────────────────────────────┐
│  Lyra (TrueNAS Docker, Python 单体)                               │
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────┐ │
│  │ 索引层   │   │ 元数据层 │   │ 歌词层   │   │ 播放层       │ │
│  │          │   │          │   │          │   │              │ │
│  │ watchdog │   │ mutagen  │   │ sidecar  │   │ 自建静态流   │ │
│  │ +debounce│   │ 读写标签 │   │ 读写     │   │ + Range      │ │
│  │ +增量扫描│   │          │   │          │   │              │ │
│  │ +全量兜底│   │ Apple    │   │ 触发     │   │              │ │
│  │          │   │ WebAPI   │   │ lyric_match│ │              │ │
│  │ → SQLite │   │ +credits │   │ → 甄选UI │   │              │ │
│  │   索引   │   │ → diff   │   │ → 落sidecar│ │              │ │
│  │          │   │ → 写标签 │   │ → 逐字编辑│   │              │ │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └──────┬──────┘ │
│       └──────────────┴──────┬───────┴────────────────┘        │
│                              │ 共享挂载 <音乐库根> (读写)        │
└──────────────────────────────┼─────────────────────────────────┘
                               │
                      ┌────────┴────────┐
                      │  ZFS 数据集      │ ← Windows 侧通过 SMB 访问
                      │ (apple/ .lyrics/)│  你在这里增删/下载
                      └─────────────────┘
```

### 4.2 数据流（按业务场景）

**场景 1 — 浏览/检索**
```
用户打开 Lyra → 查 SQLite 索引(秒级) → 列表/封面/元数据摘要
                                            ↓ 点详情
                                    mutagen 直读音频文件标签(m4a/flac/mp3)
                                            ↓
                                    播放(自建静态流, Range 请求)
```

**场景 2 — 元数据补全**
```
详情页判定"Apple 源"(从 adamId/cnID 标签)
  → Apple WebAPI 拉权威 metadata (匿名 Bearer token, get_song_info)
  → 与音频现有标签做 Picard 式 diff (左原始/右权威/标红缺失与不一致)
  → 用户确认 before/after (UI 二次确认, 写标签是不可逆破坏性操作)
  → mutagen 写回音频标签 (含 ©wrt + ----:com.apple.iTunes:* freeform)

credits(制作人员)是独立一步:
  → credits 网页爬取 (music.587626.xyz 代理, role_map.toml 映射)
  → 同样 before/after 确认 → mutagen 写 freeform 标签
```

**场景 3a — Apple 无歌词，补歌词**
```
详情页 → 触发 lyric_match → netease/qq 抓取候选
  → 甄选 UI → 选定 → 写 sidecar (-qq.ttml/-netease.ttml)
  → lyric-bridge 运行时接管(Navidrome 侧,不在本项目范围)
```

**场景 3b — Apple 逐行，补逐字**
```
同 3a,但 sidecar 是逐字版,lyric-bridge preferWordSynced 接管
```

**场景 3c — 时间轴对不上，自调**
```
详情页 → 逐字编辑器 → 改 TTML <span begin/end>
  → 波形对齐预览(对照播放) → 满意 → 覆盖写 sidecar
```

**索引层（后台）**
```
watchdog 监听 <音乐库根> → 收事件 → debounce(平静期) → 定点扫受影响目录
  → 更新 SQLite(mtime/size 水位线)
  + 周期全量对账(抓删除/移动, 兜底 watch 漏报)
  → 进度经 SSE 推前端(累计 count, 不预估 total)
```

---

## 5. 技术栈决策

### 5.1 决策结论

| 层 | 选型 | 理由 |
|----|------|------|
| 后端 | **Python（FastAPI）** | mutagen 多格式 tag 写入生产级且不可替代；lyric_match 加密管线 + api.py + credits.py 可直接复用，重写成本接近零；自用单用户场景 I/O bound，Python 并发短板不显现 |
| 前端 | **Vue3 + TS + Vite + unplugin/auto-import + ESLint + Tailwind + pnpm** | 需求方指定 |
| 标签读写 | **mutagen** | MP4/FLAC/MP3 全格式通吃，iTunes freeform `----:com.apple.iTunes:*` 原生支持，参考项目 `src/mp4.py`+`metadata.py` 已验证 31 个 key + freeform 规整逻辑 |
| 文件监听 | **watchdog** | Python 侧 fsnotify 等价物，ZFS 事件可穿透 |
| 索引 | **SQLite（aiosqlite）** | 自建，无外部依赖 |
| 部署 | **Docker 单容器** | TrueNAS，bind mount 音乐库根 |
| 播放 | **自建静态流 + Range** | 不借 Navidrome stream API |

### 5.2 关键决策依据

**为什么 Python 而非 Go**（2026-07-12 修订，原 Go 方案作废）：
- **tag 写入是命脉硬伤**：Go 生态无成熟 MP4 freeform writer（tunetag 仓库已 404；abema/go-mp4 需自研 stco/co64 重定位，O2 无备份放大风险；go-taglib freeform 写从未被任何人验证）。mutagen 是生产级唯一可靠选择
- **多格式覆盖**：库内 m4a 为主但有相当量 flac/mp3，Go 要拼凑三套库（id3v2 + flac + 自研 MP4），mutagen 一个库通吃
- **复用红利**：`api.py`/`credits.py`/`mp4.py`/`metadata.py`/`tools/lyric_match/` 全是现成 Python，改壳套 FastAPI 即可，重写成本接近零
- **场景不触发 Go 优势**：自用单用户、I/O bound、文件量 1-5 万级，Python asyncio 完全 hold 住；Go 的并发/单二进制/性能优势在此量级不显现
- **"终局全 Go"重新定义**：不作项目既定目标，改为"出现性能墙时的可选优化路径"——不绑架当前决策

**scanner 性能取舍**（基于 Navidrome 实现调研）：
- Navidrome scanner：go-pipeline 流水线，5 并发 folder worker + 单线程 DB 事务，go-taglib(WASM) 读 tag
- Python 等价实现：asyncio + `run_in_executor`(mutagen 同步库) + aiosqlite，有效并发受线程池限制
- 估算差距 1.5-3x，但**实际感知接近零**：全量扫描低频（首次建库一次，之后靠 watcher 增量），watcher 触发单 folder 增量秒级完成，单用户无并发压力
- Python 真实短板是大库(10万+)内存占用，Lyra 不到该量级

**为什么自建索引而非借 Navidrome 搜索**：
- 核心价值（元数据 diff/标签写回/歌词甄选）必须直读文件，Navidrome API 给不了 Apple freeform 标签细节
- 详情层必须自建文件索引 → 列表层也用同一份 SQLite，一致性最好、依赖最少
- 符合「能不借 Navidrome 就不借」的原则
- 代价：本地索引与 Navidrome 库可能短暂不一致（写标签后 Navidrome 未重扫前显示旧值）——已明确「不管 Navidrome 那侧」，接受此代价

**为什么 Apple 元数据走公开 JWT 而非授权 API/纯网页爬取**：
- `WebAPI` 的 token 是从 `music.apple.com` 首页 JS 抠出的**公开 JWT**，非用户登录态
- 会员过期/无会员**不影响**元数据查询（与订阅状态无关）
- API 返回的结构化 JSON 比网页爬取更完整、更准
- 无需保密凭据，泄露面顾虑解除

---

## 6. 模块清单与复用/重写映射

| 模块 | 来源 | 关键库 | 风险 |
|------|------|-------|------|
| Apple WebAPI（匿名 Bearer token + get_song_info） | 改壳 `src/api.py` | `httpx` + 正则抠 JWT | 低 |
| credits 网页爬取 | 改壳 `src/credits.py` | `httpx` + `selectolax`/`lxml` | 低（原码已验证） |
| lyric_match（网易 weapi + QQ 3DES + 评分 + TTML 转换） | **直接搬** `tools/lyric_match/` | `pycryptodome`(3DES) + 原码 weapi | 低（原码已验证） |
| 标签读写 | 改壳 `src/mp4.py`+`metadata.py` | **mutagen** | 低 |
| 文件监听 + 索引 | 新写 | `watchdog` + `aiosqlite` | 低 |
| 扫描进度推送 | 新写 | FastAPI `StreamingResponse`(SSE) | 低 |
| 歌词 sidecar 读写 | 新写 | 标准库 + TTML 解析(`lxml`) | 低 |
| 逐字歌词编辑器（含波形对齐） | 新写 | 前端 Vue3 + wavesurfer.js（交互式波形+解码+播放位置同步） | 中（依赖成熟，降级为前端工作量） |
| 播放（静态流 + Range） | 新写 | FastAPI `FileResponse`/`StreamingResponse` + Range | 低 |
| 前端 UI | 新写 | Vue3/TS/Vite/Tailwind | 中 |

### 明确「不在本项目范围」

- 音频解密（pywidevine / wrapper-manager gRPC / m3u8 封装）
- Navidrome rescan 触发与配置
- AI 声学分析/聚类/智能歌单

---

## 7. 设计原则

### 7.1 歌词与元数据分治

- **歌词 = sidecar 低侵入**：多来源（apple/netease/qq）靠 sidecar 文件管理，不嵌音频标签。理由：歌词来源多，嵌进标签极难管理。
- **元数据 = 可写标签**：单一权威（Apple），需要可读、可对照、可补全。直接写回音频标签（`©wrt` + freeform）。

两条路线分治，互不影响。

### 7.2 写操作安全网

- 写标签前 **UI 二次确认**：展示 before/after，用户确认才写
- 写标签是**不可逆破坏性操作**，无 Ctrl+Z
- **不加 tagbak 自动备份**（已定，O2）：自用场景接受此风险，靠 UI 确认单点把关

### 7.3 索引策略（抄 Navidrome，取中间路线）

**监听 + 扫描机制**：
- watchdog watch + **debounce**（事件平静期触发，非每事件即扫，参照 Navidrome `WatcherWait=5s`）
- **定点增量扫描**（只扫受影响目录，非全量）
- **周期全量对账兜底**（抓 watch 漏报的删除/移动）
- watch 失效时静默退化为纯定时扫描 + mtime 对账
- folder 级 hash watermark 判定是否需重扫（MD5 of 子文件 name+size+mtime 三元组，非内容哈希）+ 文件级 mtime 二次过滤

**扫描粒度——中间路线（非 Navidrome 完整镜像，非纯搜索索引）**：
- **存**：检索字段（title/artist/album_artist/album/path/track/disc/year）+ 音频属性（duration/bitrate/codec/samplerate）+ **完整 tag map（JSON blob 存原始 tag）**+ mtime/size + has_cover(bool)
- **不存**（Navidrome 有但 Lyra 不需要）：MusicBrainz 全套 ID、ReplayGain、Participants 关系表、PID 移动检测、排序键
- tag 用 JSON blob 而非关系表：diff 时逐字段比对信息无丢失，新增 tag 不改 schema

**扫描进度——SSE 推送**：
- FastAPI `StreamingResponse` 实现 SSE，前端 `EventSource` 订阅
- **只发累计 count（已扫文件数/folder 数），不预估 total**（walk 流式无法预知总数，参照 Navidrome 设计）
- 限流广播（攒 0.5s 或每 N 文件发一次），避免 SSE 刷屏
- 同时提供轮询 `GET /api/scanner/status`（不订阅 SSE 的场景）

---

## 8. 待定项与开放问题

| # | 项 | 默认/倾向 | 何时定 |
|---|----|----------|--------|
| O1 | 逐字编辑器 v1 是否含波形对齐 | **已定：wavesurfer.js + 前端解码，v1 一步到位**（交互式波形 + 逐字编辑） | ✅ 已定 |
| O2 | 写标签是否加 tagbak sidecar 自动备份 | **已定：不加备份，只靠 UI before/after 确认**（写标签一次性确认即不可逆，自用场景接受此风险） | ✅ 已定 |
| O3 | tag 写入库技术选型 | **已定：mutagen**（Python FastAPI 全面转向）。tunetag 仓库 404 已弃；Go 生态无成熟 MP4 freeform writer，多格式(m4a/flac/mp3)覆盖需拼凑三套库；mutagen 生产级通吃全格式，参考项目 `mp4.py`+`metadata.py`+`lyric_match/` 全可复用 | ✅ 已定 |
| O4 | Apple WebAPI token 缓存/刷新策略 | **已定**：原项目 token 抓一次钉死无刷新（401 静默返回 None 是隐藏故障），Lyra 必须改进——①解码 JWT `exp` 提前 60s 主动刷新 ②401 被动刷新（raise_for_status + 重放 1 次）③`asyncio.Lock` 并发去重防抓取风暴 ④启动预热（startup 事件）⑤异常白名单加 IndexError（正则未命中）。内存存储，单 worker 无需落盘 | ✅ 已定 |
| O5 | credits region fallback 是否保留并行探测 | **已定：简化为串行**。原项目并行（4 批 + 0.05s stagger + FIRST_COMPLETED + cancel）是"多用户 + wrapper-manager 动态区 + 追求下载吞吐"语境优化；Lyra 去掉 wrapper-manager 依赖后动态区退化为空，候选只剩内置 9 区表，自用单用户对延迟不敏感，串行 + 每次后 sleep 0.3s 足够，代码量减半。**必须保留**：`_NO_CREDITS_SENTINEL` 哨兵（区分永久无/临时失败，防反复重扫）+ 落地页守卫（song_id not in body → None，防 CF 缓存错页） | ✅ 已定 |
| O6 | 索引层 debounce 平静期时长 | **已定：5s**（沿用 Navidrome `WatcherWait` 默认值，同处境同量级，经验值合理），扫描进行中退避 3×=15s | ✅ 已定 |
| O7 | 播放是否需要转码（flac→mp3 省流） | **已定：不转码**。自用内网千兆，flac 1.4Mbps 无压力；前端 Web Audio API 原生解码 flac/m4a/mp3；转码需 ffmpeg 后端，过度工程 | ✅ 已定 |
| O8 | 前端是否复用 AudioMuse-AI 的波形/歌词组件 | 不复用（独立项目，邻居非亲戚） | 已定：不复用 |

---

## 9. 后续阶段

本文档固化后，进入：
1. **规格阶段**：逐模块细化 API、数据模型、交互流程（O1-O7 已全部定案，规格阶段直接按决议执行）
2. **开发阶段**：按模块清单实现，前端 Vue3 + 后端 Python(FastAPI) 并行
3. **部署阶段**：Dockerfile + TrueNAS 部署验证

---

## 附：讨论脉络（本轮收敛过程）

本规格由需求方与 QA 多轮讨论收敛而成，关键决策点：
1. 形态：Web（非 CLI/插件）
2. 部署：TrueNAS Docker，自用
3. 动作边界：读写（非纯浏览）
4. 歌词落盘：sidecar（L1=A），低侵入
5. 歌词三场景：a 无歌词补 / b 逐行补逐字 / c 时间轴自调
6. 元数据权威：Apple Music API（M1）
7. 元数据写回：写音频标签（M2=a），与歌词 sidecar 分治
8. 元数据写回确认：UI before/after（M4）
9. 时间轴编辑：逐字 + 波形对齐（L3=C, L4 全量）
10. 播放取数：自建静态流（P1，不借 Navidrome）
11. 部署拓扑：TrueNAS bind mount ZFS（IX0/IX1/IX2=a）
12. 索引策略：抄 Navidrome 混合模式（watch+debounce+增量+全量兜底）
13. 技术栈：Python FastAPI 后端 + Vue3 前端（2026-07-12 修订，原 Go 方案作废——tag 写入多格式是 Go 命脉硬伤，mutagen 不可替代）
14. 不挂 gRPC：Web 不碰解密链路，无需 wrapper-manager
15. 独立项目：Lyra，放 `media/` 目录，与邻居项目无工程关系
16. 自建索引：不借 Navidrome 搜索
