#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth.py — 用户鉴权服务
========================

职责：
  1. 注册（create_user）：用户名 + 密码 → 写入 users 表
  2. 登录（authenticate）：校验密码 → 签发 Session 票据
  3. Session 校验（verify_session）：从请求中提取票据 → 校验 → 返回 user_id
  4. 用户信息查询（get_current_user）：通过 user_id 取账号信息

设计要点：
  - Session 票据通过签名 Cookie 下发（HttpOnly + SameSite=Strict）
  - 密码强度校验（长度 ≥ 8，必须包含字母与数字）
  - 用户名校验（长度 3-32，仅字母数字下划线）
  - 错误码统一，便于 API 层映射 HTTP 状态

Cookie 名称：timetable_session
"""

import re
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Optional, Tuple

from crypto import CryptoService, get_crypto_service
from db import UsersDAO, UserConfigsDAO, get_users_dao, get_user_configs_dao, DbError


# ============================================================================
#  常量
# ============================================================================

SESSION_COOKIE_NAME = "timetable_session"
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_SAMESITE = "Strict"  # 防 CSRF
SESSION_MAX_AGE = 7 * 24 * 3600     # 7 天

# 用户名规则：3-32 位字母数字下划线
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
# 密码规则：≥ 8 位，至少含一个字母和一个数字
PASSWORD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,64}$")


# ============================================================================
#  异常
# ============================================================================

class AuthError(Exception):
    """鉴权异常，带错误码。"""

    def __init__(self, message, code="AUTH_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self):
        return "[%s] %s" % (self.code, self.message)


# ============================================================================
#  服务
# ============================================================================

@dataclass
class AuthResult:
    """登录 / 注册成功后的返回结构。"""
    user_id: int
    username: str
    display_name: Optional[str]
    session_ticket: str
    expires_in: int


class AuthService:
    """用户鉴权服务。"""

    def __init__(self,
                 users_dao: Optional[UsersDAO] = None,
                 configs_dao: Optional[UserConfigsDAO] = None,
                 crypto: Optional[CryptoService] = None):
        self.users_dao = users_dao or get_users_dao()
        self.configs_dao = configs_dao or get_user_configs_dao()
        self.crypto = crypto or get_crypto_service()

    # ---------- 校验 ----------

    @staticmethod
    def _validate_username(username: str) -> None:
        if not username or not USERNAME_RE.match(username):
            raise AuthError(
                "用户名需 3-32 位字母数字下划线", code="AUTH_INVALID_USERNAME")

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password or not PASSWORD_RE.match(password):
            raise AuthError(
                "密码至少 8 位且必须包含字母与数字", code="AUTH_WEAK_PASSWORD")

    # ---------- 注册 ----------

    def register(self, username: str, password: str,
                 display_name: Optional[str] = None) -> AuthResult:
        """注册新用户，并签发 Session。

        :raises AuthError: 用户名/密码不合规或用户名已存在
        """
        self._validate_username(username)
        self._validate_password(password)
        if display_name and len(display_name) > 128:
            raise AuthError("显示名过长", code="AUTH_INVALID_DISPLAYNAME")

        try:
            user_id = self.users_dao.create(username, password, display_name)
        except DbError as e:
            if e.code == "DB_DUPLICATE_USERNAME":
                raise AuthError("用户名已被占用", code="AUTH_USERNAME_TAKEN")
            raise AuthError("注册失败: %s" % e.message, code="AUTH_REGISTER_FAILED")

        # 自动签发 Session
        ticket = self.crypto.create_session_ticket(user_id, SESSION_MAX_AGE)
        # 更新登录时间
        try:
            self.users_dao.update_last_login(user_id)
        except Exception:
            pass  # 非关键步骤
        return AuthResult(
            user_id=user_id, username=username, display_name=display_name,
            session_ticket=ticket, expires_in=SESSION_MAX_AGE,
        )

    # ---------- 登录 ----------

    def authenticate(self, username: str, password: str) -> AuthResult:
        """校验用户名 + 密码，签发 Session。

        :raises AuthError: 用户不存在 / 密码错误 / 账号被禁用
        """
        if not username or not password:
            raise AuthError("用户名或密码不能为空", code="AUTH_MISSING_CREDENTIALS")

        cred = self.users_dao.find_credentials(username)
        if cred is None:
            # 安全实践：不区分"用户不存在"与"密码错误"，避免枚举攻击
            raise AuthError("用户名或密码错误", code="AUTH_INVALID_CREDENTIALS")
        if not cred.get("is_active"):
            raise AuthError("账号已被禁用，请联系管理员", code="AUTH_ACCOUNT_DISABLED")

        ok = self.crypto.verify_password(
            password, cred["password_hash"], cred["salt"])
        if not ok:
            raise AuthError("用户名或密码错误", code="AUTH_INVALID_CREDENTIALS")

        # 登录成功：更新 last_login_at
        try:
            self.users_dao.update_last_login(cred["id"])
        except Exception:
            pass

        ticket = self.crypto.create_session_ticket(cred["id"], SESSION_MAX_AGE)
        return AuthResult(
            user_id=cred["id"], username=cred["username"],
            display_name=None,  # find_credentials 不查 display_name
            session_ticket=ticket, expires_in=SESSION_MAX_AGE,
        )

    # ---------- Session ----------

    def verify_session(self, ticket: Optional[str]) -> Optional[int]:
        """校验 Session 票据，返回 user_id 或 None。"""
        if not ticket:
            return None
        return self.crypto.verify_session_ticket(ticket)

    def get_user_info(self, user_id: int) -> Optional[dict]:
        """获取用户公开信息（不含密码）。"""
        user = self.users_dao.find_by_id(user_id)
        if not user:
            return None
        return {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name"),
            "is_active": bool(user.get("is_active")),
            "last_login_at": str(user["last_login_at"]) if user.get("last_login_at") else None,
            "created_at": str(user["created_at"]) if user.get("created_at") else None,
        }

    # ---------- Cookie 处理 ----------

    @staticmethod
    def build_set_cookie_header(ticket: str, max_age: int = SESSION_MAX_AGE) -> str:
        """构造 Set-Cookie 头值（HttpOnly + SameSite=Strict + Secure 可选）。"""
        # 生产环境若启用 HTTPS，应加 Secure
        secure = ""
        if __import__("os").environ.get("TIMETABLE_COOKIE_SECURE", "").lower() in ("1", "true"):
            secure = "; Secure"
        return (
            "%s=%s; Path=%s; Max-Age=%d; HttpOnly; SameSite=%s%s"
            % (SESSION_COOKIE_NAME, ticket, SESSION_COOKIE_PATH,
               max_age, SESSION_COOKIE_SAMESITE, secure)
        )

    @staticmethod
    def build_clear_cookie_header() -> str:
        """构造清除 Cookie 的 Set-Cookie 头值。"""
        return (
            "%s=; Path=%s; Max-Age=0; HttpOnly; SameSite=%s"
            % (SESSION_COOKIE_NAME, SESSION_COOKIE_PATH, SESSION_COOKIE_SAMESITE)
        )

    @staticmethod
    def extract_ticket_from_cookie(cookie_header: Optional[str]) -> Optional[str]:
        """从请求的 Cookie 头中提取 Session 票据。"""
        if not cookie_header:
            return None
        try:
            c = SimpleCookie()
            c.load(cookie_header)
            morsel = c.get(SESSION_COOKIE_NAME)
            return morsel.value if morsel else None
        except Exception:
            return None


# ============================================================================
#  单例
# ============================================================================

_singleton = None
_singleton_lock = None


def get_auth_service() -> AuthService:
    global _singleton, _singleton_lock
    if _singleton is None:
        import threading
        _singleton_lock = threading.Lock()
        with _singleton_lock:
            if _singleton is None:
                _singleton = AuthService()
    return _singleton


# ============================================================================
#  自检
# ============================================================================

if __name__ == "__main__":
    svc = get_auth_service()
    # 仅做正则校验测试，不连数据库
    try:
        svc._validate_username("ab")  # 太短
        print("FAIL: 太短的用户名应被拒绝")
    except AuthError as e:
        print("OK 拒绝短用户名:", e.code)
    try:
        svc._validate_password("123")  # 太弱
        print("FAIL: 弱密码应被拒绝")
    except AuthError as e:
        print("OK 拒绝弱密码:", e.code)
    try:
        svc._validate_username("alice_2025")
        svc._validate_password("Alice2025!")
        print("OK 合法用户名/密码通过校验")
    except AuthError as e:
        print("FAIL:", e)
