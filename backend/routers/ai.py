"""
AI 对话：读写字段 chat_history、流式调用模型、多会话创建/删除等。
聊天逻辑重、和 OpenAI 客户端绑定，单独文件更清晰。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ai实战"))

import auth_db  # noqa: E402
import rag_store  # noqa: E402
from deps import get_current_user_id  # noqa: E402
from fastapi import APIRouter, Depends, HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from openai import OpenAI  # noqa: E402
from pydantic import BaseModel  # noqa: E402

router = APIRouter()

BASE_SYSTEM_PROMPT = """
你是 Glans Penis开发的AI助手，你的名字叫小龟头。
""".strip()


def _default_history() -> dict:
    return {"chat_1": {"title": "新对话", "messages": []}}


def _load_state(uid: int) -> tuple[dict, str]:
    loaded = auth_db.load_chat_state(uid)
    if loaded:
        hist, cid = loaded
        if cid not in hist:
            cid = next(iter(hist))
        return hist, cid
    h = _default_history()
    return h, "chat_1"


class StateBody(BaseModel):
    chat_history: dict
    current_chat_id: str


class StreamBody(BaseModel):
    chat_id: str
    user_message: str
    rag_doc_id: str | None = None
    rag_file_name: str | None = None


class NewChatBody(BaseModel):
    title: str | None = None


@router.get("/state")
def get_state(user_id: int = Depends(get_current_user_id)):
    hist, cid = _load_state(user_id)
    return {"chat_history": hist, "current_chat_id": cid}


@router.put("/state")
def put_state(body: StateBody, user_id: int = Depends(get_current_user_id)):
    if not isinstance(body.chat_history, dict) or not body.current_chat_id:
        raise HTTPException(status_code=400, detail="无效的状态")
    if body.current_chat_id not in body.chat_history:
        raise HTTPException(status_code=400, detail="current_chat_id 不在历史中")
    auth_db.save_chat_state(user_id, body.chat_history, body.current_chat_id)
    return {"ok": True}


@router.post("/conversations")
def new_conversation(body: NewChatBody, user_id: int = Depends(get_current_user_id)):
    hist, _ = _load_state(user_id)
    n = len(hist) + 1
    new_id = f"chat_{n}"
    while new_id in hist:
        n += 1
        new_id = f"chat_{n}"
    title = body.title or f"对话 {len(hist) + 1}"
    hist[new_id] = {"title": title, "messages": []}
    auth_db.save_chat_state(user_id, hist, new_id)
    return {"id": new_id, "title": title, "chat_history": hist, "current_chat_id": new_id}


@router.delete("/conversations/{chat_id}")
def delete_conversation(chat_id: str, user_id: int = Depends(get_current_user_id)):
    hist, cid = _load_state(user_id)
    if chat_id not in hist:
        raise HTTPException(status_code=404, detail="对话不存在")
    if len(hist) <= 1:
        hist[chat_id]["messages"] = []
        hist[chat_id]["title"] = "新对话"
        new_cid = chat_id
    else:
        del hist[chat_id]
        new_cid = cid if cid in hist else next(iter(hist))
    auth_db.save_chat_state(user_id, hist, new_cid)
    return {"ok": True, "chat_history": hist, "current_chat_id": new_cid}


def _sse_line(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


@router.post("/stream")
def stream_reply(body: StreamBody, user_id: int = Depends(get_current_user_id)):
    text = body.user_message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    hist, _ = _load_state(user_id)
    cid = body.chat_id
    if cid not in hist:
        raise HTTPException(status_code=404, detail="对话不存在")

    current = hist[cid]
    user_content = text
    if body.rag_doc_id and body.rag_file_name:
        user_content = f"[附件:{body.rag_file_name}] {text}"
    current["messages"].append({"role": "user", "content": user_content})

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:

        def err_gen():
            msg = "（未配置 DEEPSEEK_API_KEY）"
            yield _sse_line({"error": True, "content": msg})
            current["messages"].append({"role": "assistant", "content": msg})
            auth_db.save_chat_state(user_id, hist, cid)
            yield b"data: [DONE]\n\n"

        return StreamingResponse(err_gen(), media_type="text/event-stream")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    api_messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
    ]
    refs = (
        rag_store.chunks_by_doc(user_id, body.rag_doc_id or "", k=8)
        if body.rag_doc_id
        else []
    )
    if refs:
        ctx = "\n\n".join([f"[来源:{r.file_name}]\n{r.text[:900]}" for r in refs])
        api_messages.append(
            {
                "role": "system",
                "content": (
                    "你当前在“文档问答模式”。禁止回答“无法读取文档/图片”。"
                    "你已经拿到了文档片段文本，必须仅基于片段作答。"
                    "若信息不足，只能说“附件中未找到相关信息”。"
                    "回答使用两段：分析、总结。"
                ),
            }
        )
    for idx, m in enumerate(current["messages"]):
        if refs and idx == len(current["messages"]) - 1 and m["role"] == "user":
            enriched = (
                "【附件文档片段】\n"
                f"{ctx}\n\n"
                "【用户问题】\n"
                f"{m['content']}\n\n"
                "请仅基于“附件文档片段”回答，输出“分析”和“总结”两部分。"
            )
            api_messages.append({"role": "user", "content": enriched})
        else:
            api_messages.append({"role": m["role"], "content": m["content"]})

    def generate():
        full = ""
        try:
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=api_messages,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full += delta.content
                    yield _sse_line({"content": delta.content})
        except Exception as e:
            full = f"（调用失败：{e}）"
            yield _sse_line({"error": True, "content": full})

        if full:
            current["messages"].append({"role": "assistant", "content": full})
            if len(current["messages"]) == 2:
                u0 = current["messages"][0].get("content", "")
                current["title"] = (u0[:15] + "...") if len(u0) > 15 else u0
        auth_db.save_chat_state(user_id, hist, cid)
        yield b"data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
