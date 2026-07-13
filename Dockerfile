# syntax=docker/dockerfile:1

# ---------- Stage 1: build frontend ----------
# 用 node:20-slim 作前端构建环境（corepack 自带，激活 pnpm 9.14.0）
FROM node:20-slim AS frontend-build

WORKDIR /build

# 启用 corepack 并锁定 pnpm 版本（与 frontend/package.json packageManager 字段一致）
RUN corepack enable && corepack prepare pnpm@9.14.0 --activate

# 先拷 lock 文件，利用层缓存（依赖变化才重跑 install）
COPY frontend/package.json frontend/pnpm-lock.yaml ./

# --frozen-lockfile 保证 CI 构建可复现（lock 与 package.json 不一致时失败）
RUN pnpm install --frozen-lockfile

# 再拷源码（node_modules 已在上一层，源码变化不重装依赖）
COPY frontend/ ./

# 产出 /build/dist（vue-tsc 类型检查 + vite build）
RUN pnpm build

# ---------- Stage 2: runtime ----------
# python:3.12-slim 与 AGENTS.md §3 的 3.12 边界一致
FROM python:3.12-slim AS runtime

# 容器内先装 uvicorn（requirements.txt 不含它，避免本机 dev 装多余的 server）
# 实际上 uvicorn[standard] 在 requirements.txt 里——此处独立装一次保证命令行可用
RUN pip install --no-cache-dir uvicorn[standard]>=0.34.0

WORKDIR /app

# 先拷 requirements，利用层缓存
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷后端源码
COPY backend/ ./backend/

# bake role_map.toml 进镜像（运行期只读；改动要重 build——v1 决策）
COPY data/role_map.toml ./data/role_map.toml

# 拷前端产物（Stage 1 的 /build/dist → /app/static）
COPY --from=frontend-build /build/dist ./static

# 运行期环境变量（docker-compose / docker run 可覆盖）
ENV LYRA_DB_PATH=/data/lyra.db \
    LYRA_ROLE_MAP_FILE=/app/data/role_map.toml \
    LYRA_STATIC_DIR=/app/static \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# HEALTHCHECK 用 python urllib（slim 镜像无 curl，避免额外装包）
# /api/health 返回 200 = 进程存活 + 路由可达
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status==200 else 1)"

# 单 worker 自用场景（AGENTS.md §3.6）；容器内 uvicorn 不加 --reload
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
