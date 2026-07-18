#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crypto.py — 加密 / 鉴权原语
================================

职责：
  1. API_KEY 等敏感字段对称加密 / 解密（Fernet：AES-128-CBC + HMAC-SHA256）
  2. 用户密码哈希与校验（PBKDF2-HMAC-SHA256 + 用户级 salt）
  3. Session 票据签发与校验（HMAC-SHA256 签名 Cookie）

设计原则：
  - 加密密钥从环境变量 TIMETABLE_SECRET_KEY 读取，绝不硬编码
  - 密码使用 PBKDF2 + 随机 salt，迭代 200000 次（OWASP 2023 推荐）
  - Session 票据包含 user_id + 过期时间 + HMAC 签名，防篡改
  - 所有随机数使用 secrets 模块（密码学安全随机源）

依赖：
  - cryptography (Fernet)：pip install cryptography
    若未安装，crypto.encrypt_api_key 会抛出明确异常引导用户安装。
  - 密码哈希、Session 签名均使用 Python 标准库，零依赖可用。

用法：
  from crypto import CryptoService
  svc = CryptoService()  # 自动从环境变量读取密钥
  enc = svc.encrypt_api_key("sk-xxxx")
  dec = svc.decrypt_api_key(enc)
  ok = svc.verify_password(plain, stored_hash, salt)
  h, s = svc.hash_password("mypassword")
  ticket = svc.create_session_ticket(user_id=42)
  user_id = svc.verify_session_ticket(ticket)
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional, Tuple

# Fernet 来自 cryptography 库（可选依赖）
try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_FERNET = True
except Exception:  # pragma: no cover
    _HAS_FERNET = False


# ============================================================================
#  常量
# ============================================================================

# PBKDF2 参数（OWASP 2023 推荐：SHA-256 + 200000 次迭代）
PBKDF2_ALGO = "sha256"
PBKDF2_ITERATIONS = 200_000
PBKDF2_DKLEN = 32  # 派生密钥长度（字节）

# Session 票据
SESSION_MAX_AGE = 7 * 24 * 3600  # 默认 7 天（秒）
SESSION_VERSION = 1  # 票据格式版本，便于后续升级

# Salt 长度
SALT_LEN = 16  # 字节，base64 后 22 字符


# ============================================================================
#  加密服务
# ============================================================================

class CryptoError(Exception):
    """加密 / 鉴权相关错误的基类。"""


class CryptoService:
    """统一加密服务：API_KEY 加密 + 密码哈希 + Session 票据。

    所有方法线程安全（无共享可变状态）。
    """

    def __init__(self, secret_key: Optional[str] = None):
        """初始化加密服务。

        :param secret_key: 主密钥。未传时从环境变量 TIMETABLE_SECRET_KEY 读取；
                           均无则自动生成临时密钥（仅用于开发，重启后失效）。
        """
        key = secret_key or os.environ.get("TIMETABLE_SECRET_KEY", "")
        if not key:
            # 开发模式：自动生成（生产环境必须通过环境变量显式配置）
            key = Fernet.generate_key().decode("ascii") if _HAS_FERNET else "dev-only-key-32bytes-long!!"
            import sys
            print("[crypto] 警告：未设置 TIMETABLE_SECRET_KEY，使用临时密钥（仅开发用）",
                  file=sys.stderr)

        self._secret_key = key
        self._session_hmac_key = self._derive_session_key(key)
        self._fernet = self._build_fernet(key)

    # ---------- API_KEY 加密 / 解密 ----------

    def _build_fernet(self, key: str):
        """构造 Fernet 实例。未安装 cryptography 时返回 None。"""
        if not _HAS_FERNET:
            return None
        # 把任意长 key 派生为 32 字节再 base64，得到合法 Fernet key
        dk = hashlib.sha256(key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(dk)
        return Fernet(fernet_key)

    def encrypt_api_key(self, plaintext: str) -> str:
        """加密 API_KEY，返回 base64 字符串密文。

        :raises CryptoError: 未安装 cryptography 库
        """
        if not _HAS_FERNET or self._fernet is None:
            raise CryptoError(
                "未安装 cryptography 库，请执行: pip install cryptography")
        if not plaintext:
            return ""
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")

    def decrypt_api_key(self, ciphertext: str) -> str:
        """解密 API_KEY，返回明文。

        :raises CryptoError: 密文损坏或密钥不匹配
        """
        if not _HAS_FERNET or self._fernet is None:
            raise CryptoError(
                "未安装 cryptography 库，请执行: pip install cryptography")
        if not ciphertext:
            return ""
        try:
            token = ciphertext.encode("ascii") if isinstance(ciphertext, str) else ciphertext
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as e:
            raise CryptoError("API_KEY 密文损坏或密钥不匹配") from e

    # ---------- 密码哈希 / 校验（标准库实现，零依赖） ----------

    @staticmethod
    def generate_salt() -> str:
        """生成 16 字节随机 salt，返回 base64 字符串。"""
        return base64.b64encode(secrets.token_bytes(SALT_LEN)).decode("ascii")

    def hash_password(self, password: str, salt: Optional[str] = None) -> Tuple[str, str]:
        """使用 PBKDF2-HMAC-SHA256 哈希密码。

        :param password: 明文密码
        :param salt:     已有 salt（用于校验时复用），不传则生成新 salt
        :return: (password_hash, salt) 均为 base64 字符串
        """
        if not password:
            raise CryptoError("密码不能为空")
        if salt is None:
            salt = self.generate_salt()
        salt_bytes = base64.b64decode(salt)
        dk = hashlib.pbkdf2_hmac(
            PBKDF2_ALGO, password.encode("utf-8"), salt_bytes,
            PBKDF2_ITERATIONS, dklen=PBKDF2_DKLEN)
        return base64.b64encode(dk).decode("ascii"), salt

    def verify_password(self, password: str, stored_hash: str, salt: str) -> bool:
        """校验密码是否匹配存储的哈希。使用恒定时间比较防时序攻击。"""
        if not password or not stored_hash or not salt:
            return False
        try:
            computed_hash, _ = self.hash_password(password, salt)
        except Exception:
            return False
        return hmac.compare_digest(computed_hash, stored_hash)

    # ---------- Session 票据（签名 Cookie） ----------

    @staticmethod
    def _derive_session_key(secret: str) -> bytes:
        """从主密钥派生 Session HMAC 专用密钥（域分离）。"""
        return hashlib.sha256(("session|" + secret).encode("utf-8")).digest()

    def create_session_ticket(self, user_id: int, max_age: int = SESSION_MAX_AGE) -> str:
        """签发 Session 票据。

        格式: base64(v|expire_at|user_id) + "." + base64(hmac_sig)
        防篡改：任何字段被修改，签名校验失败。
        """
        expire_at = int(time.time()) + max_age
        payload = "%d|%d|%d" % (SESSION_VERSION, expire_at, user_id)
        payload_b64 = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        sig = hmac.new(self._session_hmac_key, payload_b64.encode("ascii"),
                       hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
        return payload_b64 + "." + sig_b64

    def verify_session_ticket(self, ticket: str) -> Optional[int]:
        """校验 Session 票据。成功返回 user_id，失败返回 None。"""
        if not ticket or "." not in ticket:
            return None
        try:
            payload_b64, sig_b64 = ticket.rsplit(".", 1)
            # 1) 验签（恒定时间比较）
            expected_sig = hmac.new(self._session_hmac_key,
                                    payload_b64.encode("ascii"),
                                    hashlib.sha256).digest()
            given_sig = base64.urlsafe_b64decode(sig_b64.encode("ascii"))
            if not hmac.compare_digest(expected_sig, given_sig):
                return None
            # 2) 解析 payload
            payload = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
            version, expire_at, user_id = payload.split("|")
            version = int(version)
            expire_at = int(expire_at)
            user_id = int(user_id)
            # 3) 版本与有效期校验
            if version != SESSION_VERSION:
                return None
            if time.time() > expire_at:
                return None
            return user_id
        except Exception:
            return None


# ============================================================================
#  单例：进程内共享
# ============================================================================

_singleton = None
_singleton_lock = None


def get_crypto_service() -> CryptoService:
    """返回进程内共享的 CryptoService 单例。"""
    global _singleton, _singleton_lock
    if _singleton is None:
        import threading
        _singleton_lock = threading.Lock()
        with _singleton_lock:
            if _singleton is None:
                _singleton = CryptoService()
    return _singleton


# ============================================================================
#  自检
# ============================================================================

if __name__ == "__main__":
    svc = CryptoService()

    print("--- API_KEY 加密测试 ---")
    enc = svc.encrypt_api_key("sk-test-1234567890abcdef")
    print("加密后:", enc[:50], "...")
    print("解密后:", svc.decrypt_api_key(enc))
    assert svc.decrypt_api_key(enc) == "sk-test-1234567890abcdef"

    print("\n--- 密码哈希测试 ---")
    h, s = svc.hash_password("MyP@ssw0rd!")
    print("hash:", h[:30], "... salt:", s)
    assert svc.verify_password("MyP@ssw0rd!", h, s)
    assert not svc.verify_password("wrong", h, s)

    print("\n--- Session 票据测试 ---")
    ticket = svc.create_session_ticket(user_id=42, max_age=60)
    print("ticket:", ticket[:50], "...")
    assert svc.verify_session_ticket(ticket) == 42
    # 篡改测试
    bad_ticket = ticket[:-5] + "AAAAA"
    assert svc.verify_session_ticket(bad_ticket) is None

    print("\n所有自检通过 ✓")
