"""
登录/注册/登出、/me、改密码、头像、短信验证码、登录动画文件等。
账户体系独立成一块，和 AI、好友解耦。
"""
from __future__ import annotations

import json
import os
import random
import re
import ssl
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ai实战"))

import auth_db  # noqa: E402
from deps import get_current_user_id  # noqa: E402
from fastapi import APIRouter, Depends, Header, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

router = APIRouter()

_MOBILE_RE = re.compile(r"^1\d{10}$")
_SMS_COOLDOWN_SECONDS = 60
_SMS_EXPIRE_MINUTES = 5


def _init_profile_table() -> None:
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INT PRIMARY KEY,
                    avatar_data LONGTEXT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )


def _get_avatar_data(user_id: int) -> str | None:
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT avatar_data FROM user_profiles WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
    if not row:
        return None
    val = row.get("avatar_data")
    return str(val) if val else None


def _set_avatar_data(user_id: int, avatar_data: str | None) -> None:
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_profiles (user_id, avatar_data)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE avatar_data = VALUES(avatar_data)
                """,
                (user_id, avatar_data),
            )


_init_profile_table()


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    password: str
    mobile: str
    sms_code: str


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str


class ChangeUsernameBody(BaseModel):
    new_username: str


class AvatarBody(BaseModel):
    avatar_data: str


class SendSmsBody(BaseModel):
    mobile: str


def _validate_mobile(mobile: str) -> str:
    m = mobile.strip()
    if not _MOBILE_RE.match(m):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    return m


def _sms_appcode() -> str:
    appcode = os.environ.get("ALI_SMS_APPCODE", "").strip()
    if not appcode:
        raise HTTPException(status_code=500, detail="短信服务未配置（缺少 ALI_SMS_APPCODE）")
    return appcode


def _sms_sign_id() -> str:
    return os.environ.get(
        "ALI_SMS_SIGN_ID", "2e65b1bb3d054466b82f0c9d125465e2"
    ).strip()


def _sms_template_id() -> str:
    return os.environ.get(
        "ALI_SMS_TEMPLATE_ID", "908e94ccf08b4476ba6c876d13f084ad"
    ).strip()


def _login_dotlottie_path() -> Path:
    p = os.environ.get(
        "LOGIN_DOTLOTTIE_PATH",
        "/Users/yang/Downloads/Turtle Animation.lottie",
    ).strip()
    return Path(p)


def _sms_verify_ssl() -> bool:
    return os.environ.get("ALI_SMS_VERIFY_SSL", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _check_sms_cooldown(mobile: str) -> int:
    """返回剩余秒数；0 表示可发送。"""
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT created_at FROM sms_verify_codes
                WHERE mobile = %s AND purpose = 'register'
                ORDER BY id DESC
                LIMIT 1
                """,
                (mobile,),
            )
            row = cur.fetchone()
    if not row:
        return 0
    created_at = row["created_at"]
    if not hasattr(created_at, "timestamp"):
        return 0
    elapsed = int(datetime.now().timestamp() - created_at.timestamp())
    remain = _SMS_COOLDOWN_SECONDS - elapsed
    return remain if remain > 0 else 0


def _send_sms_via_market(mobile: str, code: str) -> None:
    appcode = _sms_appcode()
    url = "https://gyytz.market.alicloudapi.com/sms/smsSend"
    data = {
        "mobile": mobile,
        "smsSignId": _sms_sign_id(),
        "templateId": _sms_template_id(),
        "param": f"**code**:{code},**minute**:{_SMS_EXPIRE_MINUTES}",
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"APPCODE {appcode}",
    }
    req = Request(
        f"{url}?{urlencode(data)}",
        method="POST",
        headers=headers,
    )
    try:
        if _sms_verify_ssl():
            context = ssl.create_default_context()
        else:
            context = ssl._create_unverified_context()
        with urlopen(req, timeout=12, context=context) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            if resp.status >= 400:
                raise HTTPException(status_code=502, detail="短信服务调用失败")
            # 尝试识别常见返回结构中的失败字段
            try:
                j = json.loads(body)
                code_val = str(j.get("code", ""))
                if code_val and code_val not in {"0", "200", "OK"}:
                    raise HTTPException(status_code=502, detail=f"短信发送失败：{j}")
            except json.JSONDecodeError:
                # 有些网关返回纯文本，无法解析时默认按 HTTP 状态判定
                pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"短信服务异常：{e}")


def _save_sms_code(mobile: str, code: str) -> None:
    expires_at = datetime.now() + timedelta(minutes=_SMS_EXPIRE_MINUTES)
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sms_verify_codes (mobile, code, purpose, consumed, expires_at)
                VALUES (%s, %s, 'register', 0, %s)
                """,
                (mobile, code, expires_at),
            )


def _verify_sms_code(mobile: str, sms_code: str) -> None:
    code = sms_code.strip()
    if not re.fullmatch(r"\d{4,8}", code):
        raise HTTPException(status_code=400, detail="验证码格式不正确")
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM sms_verify_codes
                WHERE mobile = %s AND purpose = 'register'
                  AND code = %s AND consumed = 0
                  AND expires_at > NOW()
                ORDER BY id DESC
                LIMIT 1
                """,
                (mobile, code),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=400, detail="验证码错误或已过期")
            cur.execute(
                "UPDATE sms_verify_codes SET consumed = 1 WHERE id = %s",
                (row["id"],),
            )


def _bind_user_mobile(user_id: int, mobile: str) -> None:
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM user_phones WHERE mobile = %s",
                (mobile,),
            )
            existed = cur.fetchone()
            if existed and int(existed["user_id"]) != user_id:
                raise HTTPException(status_code=400, detail="该手机号已绑定其他账号")
            cur.execute(
                """
                INSERT INTO user_phones (user_id, mobile)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE mobile = VALUES(mobile)
                """,
                (user_id, mobile),
            )


@router.post("/send-sms-code")
def send_sms_code(body: SendSmsBody):
    mobile = _validate_mobile(body.mobile)
    remain = _check_sms_cooldown(mobile)
    if remain > 0:
        raise HTTPException(status_code=429, detail=f"请 {remain} 秒后再试")
    code = f"{random.randint(0, 999999):06d}"
    _send_sms_via_market(mobile, code)
    _save_sms_code(mobile, code)
    return {
        "ok": True,
        "message": "验证码已发送",
        "cooldown_seconds": _SMS_COOLDOWN_SECONDS,
        "expire_minutes": _SMS_EXPIRE_MINUTES,
    }


@router.get("/login-animation")
def login_animation():
    p = _login_dotlottie_path()
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"动画文件不存在：{p}")
    return FileResponse(str(p), media_type="application/octet-stream")


@router.post("/login")
def login(body: LoginBody):
    uid, msg = auth_db.login_user(body.username.strip(), body.password)
    if uid is None:
        raise HTTPException(status_code=400, detail=msg)
    token = auth_db.create_session(uid)
    uname = auth_db.get_username(uid) or body.username
    return {"token": token, "username": uname, "user_id": uid, "message": msg}


@router.post("/register")
def register(body: RegisterBody):
    mobile = _validate_mobile(body.mobile)
    _verify_sms_code(mobile, body.sms_code)
    ok, msg = auth_db.register_user(body.username.strip(), body.password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    uid = auth_db.get_user_id_by_username(body.username.strip())
    if uid is not None:
        _bind_user_mobile(uid, mobile)
    return {"ok": True, "message": msg}


@router.post("/logout")
def logout(
    user_id: int = Depends(get_current_user_id),
    authorization: str | None = Header(None),
):
    if authorization and authorization.startswith("Bearer "):
        auth_db.revoke_session(authorization[7:].strip())
    return {"ok": True}


@router.get("/me")
def me(user_id: int = Depends(get_current_user_id)):
    name = auth_db.get_username(user_id) or str(user_id)
    return {"user_id": user_id, "username": name, "avatar_data": _get_avatar_data(user_id)}


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    user_id: int = Depends(get_current_user_id),
):
    username = auth_db.get_username(user_id)
    if not username:
        raise HTTPException(status_code=404, detail="用户不存在")

    uid, _ = auth_db.login_user(username, body.old_password)
    if uid is None:
        raise HTTPException(status_code=400, detail="旧密码错误")

    vmsg = auth_db.validate_password(body.new_password)
    if vmsg:
        raise HTTPException(status_code=400, detail=vmsg)

    pw_hash = auth_db._hash_password(body.new_password)
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (pw_hash, user_id),
            )
    return {"ok": True, "message": "密码已更新"}


@router.post("/change-username")
def change_username(
    body: ChangeUsernameBody,
    user_id: int = Depends(get_current_user_id),
):
    new_name = body.new_username.strip()
    vmsg = auth_db.validate_username(new_name)
    if vmsg:
        raise HTTPException(status_code=400, detail=vmsg)
    old_name = auth_db.get_username(user_id)
    if not old_name:
        raise HTTPException(status_code=404, detail="用户不存在")
    existed_id = auth_db.get_user_id_by_username(new_name)
    if existed_id is not None and int(existed_id) != int(user_id):
        raise HTTPException(status_code=400, detail="该用户名已被占用")
    if old_name.lower() == new_name.lower():
        return {"ok": True, "username": old_name, "message": "用户名未变化"}
    with auth_db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET username = %s WHERE id = %s",
                (new_name, user_id),
            )
    return {"ok": True, "username": new_name, "message": "用户名已更新"}


@router.get("/avatar")
def get_avatar(user_id: int = Depends(get_current_user_id)):
    return {"avatar_data": _get_avatar_data(user_id)}


@router.put("/avatar")
def put_avatar(body: AvatarBody, user_id: int = Depends(get_current_user_id)):
    avatar = body.avatar_data.strip()
    if avatar and len(avatar) > 7_500_000:
        raise HTTPException(status_code=400, detail="头像过大，最大支持 5MB")
    if avatar and not avatar.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="仅支持图片 Data URL")
    _set_avatar_data(user_id, avatar or None)
    return {"ok": True}
