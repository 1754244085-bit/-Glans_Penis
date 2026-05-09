"""
FastAPI 后端：会话沿用 ai实战/auth_db.py（MySQL），供类 ChatGPT 前端调用。
运行：cd ai_chat_web/backend && uvicorn main:app --reload --host 0.0.0.0 --port 8765
FastAPI 应用入口：建 app、CORS、挂载各路由、健康检查；启动时加载 .env。
所有 HTTP 请求从这里进；集中配置跨域和路由。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent.parent
sys.path.insert(0, str(ROOT / "ai实战"))


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from .env into process env."""
    if not path.exists() or not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        # Keep explicit environment values as highest priority.
        os.environ.setdefault(key, value)


for env_file in (
    BACKEND_DIR / ".env",
    BACKEND_DIR.parent / ".env",
    ROOT / ".env",
):
    _load_env_file(env_file)

import auth_db  # noqa: E402  # 模块末尾会 init_db()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from routers import ai, auth, friends, rag  # noqa: E402

app = FastAPI(title="龟头AI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
app.include_router(friends.router, prefix="/api/friends", tags=["friends"])
app.include_router(rag.router, prefix="/api/rag", tags=["rag"])


@app.get("/api/health")
def health():
    return {"ok": True}
