"""
内存里按用户存文档分块、简单检索（当前实现偏演示/轻量）。
快速实现「上传文档再问 AI」，不必一上来就上向量数据库。
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass


@dataclass
class RagChunk:
    doc_id: str
    file_name: str
    text: str


@dataclass
class RagDoc:
    doc_id: str
    file_name: str
    chunk_count: int
    created_at: float


_USER_DOCS: dict[int, list[RagDoc]] = {}
_USER_CHUNKS: dict[int, list[RagChunk]] = {}


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z0-9_]+", text.lower()))
    words.update(re.findall(r"[\u4e00-\u9fff]", text))
    return words


def _split_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[str]:
    src = re.sub(r"\r\n?", "\n", text).strip()
    if not src:
        return []
    if len(src) <= chunk_size:
        return [src]
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        out.append(src[i : i + chunk_size].strip())
        if i + chunk_size >= n:
            break
        i += chunk_size - overlap
    return [x for x in out if x]


def add_document(user_id: int, file_name: str, text: str) -> RagDoc:
    chunks = _split_text(text)
    if not chunks:
        raise ValueError("文档内容为空或无法解析")
    doc_id = uuid.uuid4().hex[:12]
    doc = RagDoc(
        doc_id=doc_id,
        file_name=file_name,
        chunk_count=len(chunks),
        created_at=time.time(),
    )
    _USER_DOCS.setdefault(user_id, []).append(doc)
    c_arr = _USER_CHUNKS.setdefault(user_id, [])
    for c in chunks:
        c_arr.append(RagChunk(doc_id=doc_id, file_name=file_name, text=c))
    return doc


def list_documents(user_id: int) -> list[RagDoc]:
    return list(_USER_DOCS.get(user_id, []))


def delete_document(user_id: int, doc_id: str) -> bool:
    docs = _USER_DOCS.get(user_id, [])
    before = len(docs)
    docs = [d for d in docs if d.doc_id != doc_id]
    _USER_DOCS[user_id] = docs
    chunks = _USER_CHUNKS.get(user_id, [])
    _USER_CHUNKS[user_id] = [c for c in chunks if c.doc_id != doc_id]
    return len(docs) != before


def retrieve(user_id: int, query: str, k: int = 4) -> list[RagChunk]:
    q = query.strip()
    if not q:
        return []
    q_tokens = _tokens(q)
    rows = _USER_CHUNKS.get(user_id, [])
    if not rows:
        return []
    scored: list[tuple[int, RagChunk]] = []
    for c in rows:
        tks = _tokens(c.text)
        score = len(q_tokens & tks)
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for _, c in scored[:k]]
    if top:
        return top
    return latest_chunks(user_id, k=k)


def latest_chunks(user_id: int, k: int = 4) -> list[RagChunk]:
    docs = _USER_DOCS.get(user_id, [])
    rows = _USER_CHUNKS.get(user_id, [])
    if not docs or not rows:
        return []
    doc_order = [d.doc_id for d in sorted(docs, key=lambda d: d.created_at, reverse=True)]
    out: list[RagChunk] = []
    for did in doc_order:
        for c in rows:
            if c.doc_id == did:
                out.append(c)
                if len(out) >= k:
                    return out
    return out


def chunks_by_doc(user_id: int, doc_id: str, k: int = 8) -> list[RagChunk]:
    did = doc_id.strip()
    if not did:
        return []
    rows = _USER_CHUNKS.get(user_id, [])
    if not rows:
        return []
    out = [c for c in rows if c.doc_id == did]
    return out[:k]

