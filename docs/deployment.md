# Lyra 部署手册

Lyra 通过 GitHub Actions 构建镜像 → 推 GHCR（GitHub Container Registry）→ TrueNAS 拉取运行。本机不装 Docker Desktop，构建全部在云端。

---

## 架构

```
开发机（Windows + conda）          GitHub（CI）              TrueNAS（运行）
  git push tag v0.1.0  ───────→  Actions 构建镜像
                                  推 ghcr.io/user/lyra  ──→  docker compose pull && up -d
```

- 单容器：FastAPI 兜底 serve 前端静态产物 + SPA fallback（同源，无 CORS）
- 数据持久化：SQLite named volume + 音乐库 bind mount（读写）
- 镜像标签：`:latest` / `:v0.1.0`（版本）/ `:<sha>`（精确可回滚）

---

## 前置准备

### 1. GitHub 私有仓库

1. 在 GitHub 建私有仓库（**仓库名全小写**，GHCR 要求镜像名小写，如 `lyra`）
2. 本地绑定远程并推送：
   ```bash
   git remote add origin git@github.com:<你的用户名>/lyra.git
   git push -u origin master
   ```
3. 确认仓库 **Settings → Actions → General → Workflow permissions** = "Read and write permissions"（推 GHCR 必需）

### 2. TrueNAS 准备

- TrueNAS 已装 Docker（TrueNAS SCALE 内置，或 apps 自定义）
- 音乐库目录存在且容器可访问（如 `/mnt/pool/music`）
- ZFS 数据集开启定时快照（保护音乐库，见下方"风险与备份"）

---

## 首次部署

### 1. 触发构建（打 tag）

```bash
# 本机
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions 自动触发构建。进仓库 **Actions** tab 看进度，约 3-5 分钟。完成后镜像在 `ghcr.io/<用户名>/lyra`。

### 2. TrueNAS 拉取镜像

GHCR 私有镜像要 login。创建 Personal Access Token（GitHub → Settings → Developer settings → Personal access tokens → Fine-grained），权限选 `read:packages`。

```bash
# TrueNAS SSH
echo "<你的PAT>" | docker login ghcr.io -u <GitHub用户名> --password-stdin
```

### 3. 配置 docker-compose.yml

从仓库拷 `docker-compose.yml` 到 TrueNAS，改两处：

```yaml
services:
  lyra:
    image: ghcr.io/<你的用户名>/lyra:latest   # ← 改成你的
    volumes:
      - /mnt/pool/music:/music                # ← 改成你的音乐库宿主路径
```

### 4. 启动

```bash
docker compose up -d
docker compose logs -f        # 看启动日志，确认 scanner 起来
```

### 5. 健康检查

```bash
curl http://localhost:8000/api/health
# 期望：{"status":"ok","library":{"root":"/music","status":"reachable"}}
```

浏览器访问 `http://<TrueNAS-IP>:8000` → 曲库列表页。

---

## 日常更新

```bash
# 拉最新镜像 + 重启
docker compose pull
docker compose up -d
```

或指定版本：

```bash
# 改 docker-compose.yml 的 image tag
image: ghcr.io/<用户名>/lyra:v0.2.0
docker compose up -d
```

---

## 回滚

每次构建产出三个 tag。回滚改 `image` 到任意历史版本即可：

```yaml
image: ghcr.io/<用户名>/lyra:v0.1.0      # 版本回滚
# 或精确到 commit：
image: ghcr.io/<用户名>/lyra:a1e7747     # sha 短前缀
```

```bash
docker compose up -d
```

---

## 配置项清单

环境变量（docker-compose.yml `environment`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LYRA_MUSIC_LIBRARY_ROOT` | （必填） | 容器内 `/music`，宿主路径在 volumes 映射 |
| `LYRA_DB_PATH` | `/data/lyra.db` | SQLite 持久化，named volume `lyra-data` 挂 `/data` |
| `LYRA_CREDITS_BASE_URL` | `https://music.587626.xyz` | Credits 爬取 CF Worker 代理 |

镜像内固定（改要重 build）：
- `LYRA_ROLE_MAP_FILE=/app/data/role_map.toml`（role_map.toml bake 进镜像）
- `LYRA_STATIC_DIR=/app/static`（前端产物 bake 进镜像）

---

## 风险与备份

### 音乐库读写挂载

docker-compose.yml 的 music 卷是**读写**（非 `:ro`），因为：
- Lyra 写元数据标签要改音频文件（mutagen 原地写）
- 歌词 sidecar 写到 `<music>/.lyrics/`

风险：容器内进程能写宿主音乐库。**强烈建议 TrueNAS 开 ZFS 数据集定时快照**（如每日保留 7 天）。若出 bug 污染音乐文件，靠快照回滚。

### role_map.toml 内嵌

role_map.toml bake 进镜像，运行期只读。改 role_map 要重新 push 触发 CI 构建（改文件 → commit → tag → push）。v1 决策接受此代价。

### SQLite 持久化

`lyra-data` named volume 托管 `/data/lyra.db`。`docker compose down` 不删 volume，`docker compose down -v` 才删（**慎用**，会丢索引）。误删后靠 scanner 全量重扫恢复。

---

## 排障

### 容器起不来

```bash
docker compose logs lyra        # 看启动日志
```

常见：
- `LYRA_MUSIC_LIBRARY_ROOT` 没设 / 路径不存在 → 进程能起但 `/api/health` 报 `not_configured` 或 `unreachable`，scanner 不启动
- SQLite 初始化失败 → `/api/library` 返 503，看日志排障权限/磁盘

### GHCR 拉取 401

```bash
docker logout ghcr.io
echo "<PAT>" | docker login ghcr.io -u <用户名> --password-stdin
```

PAT 过期或权限不足都会 401。确认 PAT 选了 `read:packages`。

### 前端白屏

浏览器 F12 看 Network。若 `/assets/*.js` 404 → 镜像内 `/app/static/assets` 缺失，构建失败。看 GitHub Actions 构建日志。

### 刷新 /track/123 报 404

不应出现——FastAPI 有 SPA fallback 路由。若出现，检查 `LYRA_STATIC_DIR` 是否设（镜像内默认 `/app/static`，不应缺）。
