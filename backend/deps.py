"""从请求头 Authorization: Bearer ... 解析 token，校验会话，得到当前 user_id。
需要登录的接口共用一套鉴权，避免每个路由重复写校验。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai实战"))

import auth_db  # noqa: E402
from fastapi import Header, HTTPException  # noqa: E402


async def get_current_user_id(authorization: str | None = Header(None)) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization[7:].strip()
    uid = auth_db.validate_session(token)
    if uid is None:
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    return int(uid)
