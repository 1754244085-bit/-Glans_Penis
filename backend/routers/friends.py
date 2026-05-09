"""
好友列表、申请、私聊消息、备注等。
社交功能与 AI 路由分开，权限与数据模型也分开维护。
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ai实战"))

import auth_db  # noqa: E402
from deps import get_current_user_id  # noqa: E402
from fastapi import APIRouter, Depends, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

router = APIRouter()


class FriendRequestBody(BaseModel):
    target_username: str


class DmBody(BaseModel):
    content: str


class RenameFriendBody(BaseModel):
    alias: str


@router.get("/list")
def list_friends(user_id: int = Depends(get_current_user_id)):
    friends = auth_db.list_friends_with_avatar(user_id)
    return {
        "friends": [
            {"id": fid, "username": name, "avatar_data": avatar_data}
            for fid, name, avatar_data in friends
        ]
    }


@router.get("/requests/incoming")
def incoming_requests(user_id: int = Depends(get_current_user_id)):
    reqs = auth_db.list_incoming_requests(user_id)
    return {
        "requests": [
            {
                "id": r.id,
                "from_username": r.from_username,
                "created_at": str(r.created_at) if r.created_at else "",
            }
            for r in reqs
        ]
    }


@router.post("/requests")
def send_request(body: FriendRequestBody, user_id: int = Depends(get_current_user_id)):
    ok, msg = auth_db.send_friend_request(user_id, body.target_username.strip())
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/requests/{request_id}/accept")
def accept(request_id: int, user_id: int = Depends(get_current_user_id)):
    ok, msg = auth_db.accept_request(request_id, user_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.post("/requests/{request_id}/decline")
def decline(request_id: int, user_id: int = Depends(get_current_user_id)):
    ok, msg = auth_db.decline_request(request_id, user_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.get("/{peer_id}/messages")
def get_messages(peer_id: int, user_id: int = Depends(get_current_user_id)):
    if not auth_db.are_friends(user_id, peer_id):
        raise HTTPException(status_code=403, detail="不是好友")
    rows = auth_db.list_friend_messages(user_id, peer_id)
    peer_name = auth_db.get_username(peer_id) or str(peer_id)
    return {
        "peer_id": peer_id,
        "peer_username": peer_name,
        "messages": [
            {
                "from_user_id": m["from_user_id"],
                "content": m["content"],
                "created_at": str(m["created_at"]) if m.get("created_at") else "",
            }
            for m in rows
        ],
    }


@router.post("/{peer_id}/messages")
def send_dm(peer_id: int, body: DmBody, user_id: int = Depends(get_current_user_id)):
    ok, err = auth_db.send_friend_dm(user_id, peer_id, body.content.strip())
    if not ok:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True}


@router.delete("/{peer_id}/messages")
def clear_messages(peer_id: int, user_id: int = Depends(get_current_user_id)):
    if not auth_db.are_friends(user_id, peer_id):
        raise HTTPException(status_code=403, detail="不是好友")
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM friend_messages
                WHERE (from_user_id = %s AND to_user_id = %s)
                   OR (from_user_id = %s AND to_user_id = %s)
                """,
                (user_id, peer_id, peer_id, user_id),
            )
    return {"ok": True}


@router.put("/{peer_id}/rename")
def rename_friend(
    peer_id: int,
    body: RenameFriendBody,
    user_id: int = Depends(get_current_user_id),
):
    ok, msg = auth_db.set_friend_alias(user_id, peer_id, body.alias)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@router.delete("/{peer_id}")
def delete_friend(peer_id: int, user_id: int = Depends(get_current_user_id)):
    if user_id == peer_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM friendships
                WHERE (user_id = %s AND friend_user_id = %s)
                   OR (user_id = %s AND friend_user_id = %s)
                """,
                (user_id, peer_id, peer_id, user_id),
            )
            affected = cur.rowcount
    if affected <= 0:
        raise HTTPException(status_code=404, detail="好友关系不存在")
    return {"ok": True}
