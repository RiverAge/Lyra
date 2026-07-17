"""Lyra 版本号（构建期注入）。

版本真源是 git tag（CI workflow 推 v* tag 时把 ref_name 作 build arg 传入，
Dockerfile ENV LYRA_VERSION baking 进镜像）。本机 dev 未注入则回落 0.1.0。

一处定义、多处消费：
- main.py FastAPI(version=...) —— OpenAPI 文档
- config 端点 version 字段 —— 前端设置页显示
"""

from __future__ import annotations

import os

# 构建期注入（Dockerfile ARG LYRA_VERSION → ENV LYRA_VERSION）。
# 未注入（本机 dev / 无 CI）回落写死值——与 frontend/package.json 对齐。
VERSION = os.environ.get("LYRA_VERSION") or "0.1.0"


def get_version() -> str:
    """返回当前版本号字符串。"""
    return VERSION
