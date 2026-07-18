#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db.py — MySQL 数据访问层 (DAO)
===============================

职责：
  - 管理 MySQL 连接池（线程安全，按需创建）
  - 提供 UsersDAO 与 UserConfigsDAO 数据访问对象
  - 所有查询使用参数化绑定，杜绝 SQL 注入
  - 在数据库不可用时优雅降级（抛 DbError，由上层映射为 5xx）

依赖：
  - PyMySQL (纯 Python MySQL 客户端): pip install PyMySQL
    也可使用 mysql-connector-python，通过环境变量 DB_DRIVER 切换。

设计：
  - 连接池使用 Queue 实现，懒创建，最大连接数可配
  - 每次操作通过 `with pool.get_conn() as conn:` 上下文管理
  - 自动提交策略：查询自动 commit；写操作显式 commit
  - 字段加密在 DAO 层完成（调用 crypto.CryptoService）

用法：
  from db import get_users_dao, get_user_configs_dao
  users_dao = get_users_dao()
  user = users_dao.find_by_username("alice")
"""

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

# 统一日志系统
from logger import get_logger
_log = get_logger("db")

# 数据库驱动（优先 PyMySQL，回退 mysql-connector）
try:
    import pymysql
    from pymysql.err import Error as _PyMySqlError
    _DRIVER = "pymysql"
except Exception:
    try:
        import mysql.connector
        from mysql.connector.errors import Error as _PyMySqlError
        _DRIVER = "mysql.connector"
    except Exception:
        pymysql = None
        _PyMySqlError = Exception
        _DRIVER = None

from crypto import CryptoService, get_crypto_service


# ============================================================================
#  配置
# ============================================================================

class DbConfig:
    """数据库连接配置。支持环境变量覆盖。"""

    def __init__(self):
        self.host = os.environ.get("DB_HOST", "127.0.0.1")
        self.port = int(os.environ.get("DB_PORT", "3306"))
        self.user = os.environ.get("DB_USER", "root")
        self.password = os.environ.get("DB_PASSWORD", "")
        self.database = os.environ.get("DB_NAME", "timetable_pro")
        self.charset = os.environ.get("DB_CHARSET", "utf8mb4")
        self.pool_size = int(os.environ.get("DB_POOL_SIZE", "8"))
        self.connect_timeout = int(os.environ.get("DB_CONNECT_TIMEOUT", "10"))
        # 连接空闲超过此时间（秒）会被丢弃重建，避免 MySQL 8h 超时
        self.conn_max_age = int(os.environ.get("DB_CONN_MAX_AGE", "3600"))


# ============================================================================
#  异常
# ============================================================================

class DbError(Exception):
    """数据库相关错误。"""

    def __init__(self, message, code="DB_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self):
        return "[%s] %s" % (self.code, self.message)


# ============================================================================
#  连接池
# ============================================================================

class _PooledConnection:
    """包装一个真实连接 + 创建时间，用于检测过期。"""

    __slots__ = ("conn", "created_at")

    def __init__(self, conn):
        self.conn = conn
        self.created_at = time.monotonic()


class ConnectionPool:
    """极简线程安全 MySQL 连接池。

    - 懒创建：首次 get 时才真正建立连接
    - 上限：max_size，超出则阻塞等待（带超时）
    - 健康检查：每次 get 检测连接是否过期/失效，自动重建
    """

    def __init__(self, cfg: DbConfig):
        self.cfg = cfg
        self._pool: List[_PooledConnection] = []
        self._in_use = 0
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        if _DRIVER is None:
            raise DbError(
                "未找到 MySQL 驱动，请执行: pip install PyMySQL",
                code="DB_NO_DRIVER")

    def _create_connection(self):
        """实际创建一个数据库连接。"""
        try:
            if _DRIVER == "pymysql":
                conn = pymysql.connect(
                    host=self.cfg.host,
                    port=self.cfg.port,
                    user=self.cfg.user,
                    database=self.cfg.database,
                    charset=self.cfg.charset,
                    connect_timeout=self.cfg.connect_timeout,
                    autocommit=True,  # 查询自动提交；写操作显式 commit
                    cursorclass=pymysql.cursors.DictCursor,
                )
            else:  # mysql.connector
                conn = mysql.connector.connect(
                    host=self.cfg.host,
                    port=self.cfg.port,
                    user=self.cfg.user,
                    password=self.cfg.password,
                    database=self.cfg.database,
                    charset=self.cfg.charset,
                    connection_timeout=self.cfg.connect_timeout,
                    autocommit=True,
                )
            _log.debug("新建数据库连接 | %s@%s:%d/%s",
                        self.cfg.user, self.cfg.host, self.cfg.port, self.cfg.database)
            return conn
        except _PyMySqlError as e:
            _log.error("数据库连接失败 | %s@%s:%d/%s | %s",
                       self.cfg.user, self.cfg.host, self.cfg.port,
                       self.cfg.database, e)
            raise DbError("无法连接 MySQL: %s" % e, code="DB_CONNECT_FAILED")
        except Exception as e:
            _log.error("创建数据库连接异常 | %s", e)
            raise DbError("创建数据库连接异常: %s" % e, code="DB_CONNECT_FAILED")

    def _is_alive(self, pooled: _PooledConnection) -> bool:
        """检测连接是否仍然可用。"""
        if time.monotonic() - pooled.created_at > self.cfg.conn_max_age:
            return False
        try:
            if _DRIVER == "pymysql":
                conn = pooled.conn
                if conn.open is False:
                    return False
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            else:
                if pooled.conn.is_connected() is False:
                    return False
                cur = pooled.conn.cursor()
                try:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                finally:
                    cur.close()
            return True
        except Exception:
            return False

    @contextmanager
    def get_conn(self, timeout: float = 10.0):
        """获取一个连接的上下文管理器。用完自动归还。"""
        deadline = time.monotonic() + timeout
        conn = None
        pooled = None
        # 1) 取连接
        with self._cond:
            while True:
                if self._pool:
                    pooled = self._pool.pop()
                    self._in_use += 1
                    break
                if self._in_use < self.cfg.pool_size:
                    # 在锁外创建连接（避免长时间持锁）
                    self._in_use += 1
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._in_use  # 维护一致性
                    raise DbError("获取数据库连接超时", code="DB_POOL_TIMEOUT")
                self._cond.wait(timeout=remaining)
        # 2) 创建新连接（如果是从空池取的）
        try:
            if pooled is None:
                conn = self._create_connection()
            elif not self._is_alive(pooled):
                # 旧连接失效，关闭并新建
                self._safe_close(pooled.conn)
                conn = self._create_connection()
            else:
                conn = pooled.conn
            yield conn
        finally:
            # 3) 归还
            with self._cond:
                if conn is not None:
                    try:
                        self._pool.append(_PooledConnection(conn))
                    except Exception:
                        self._safe_close(conn)
                self._in_use -= 1
                self._cond.notify()

    @staticmethod
    def _safe_close(conn):
        try:
            conn.close()
        except Exception:
            pass

    def close_all(self):
        """关闭池中所有连接（程序退出时调用）。"""
        with self._cond:
            for pooled in self._pool:
                self._safe_close(pooled.conn)
            self._pool.clear()


# ============================================================================
#  Users 数据访问对象
# ============================================================================

class UsersDAO:
    """用户账号 DAO。"""

    def __init__(self, pool: ConnectionPool, crypto: CryptoService):
        self.pool = pool
        self.crypto = crypto

    def find_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        sql = ("SELECT id, username, display_name, is_active, "
               "       last_login_at, created_at, updated_at "
               "FROM users WHERE id = %s")
        with self.pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
                row = cur.fetchone()
        return dict(row) if row else None

    def find_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        sql = ("SELECT id, username, display_name, is_active, "
               "       last_login_at, created_at, updated_at "
               "FROM users WHERE username = %s")
        with self.pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (username,))
                row = cur.fetchone()
        return dict(row) if row else None

    def find_credentials(self, username: str) -> Optional[Dict[str, Any]]:
        """查询密码字段（仅登录校验时使用，不暴露给前端）。"""
        sql = ("SELECT id, username, password_hash, salt, is_active "
               "FROM users WHERE username = %s")
        with self.pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (username,))
                row = cur.fetchone()
        return dict(row) if row else None

    def create(self, username: str, password: str,
               display_name: Optional[str] = None) -> int:
        """创建用户。返回新用户 ID。

        :raises DbError: 用户名已存在
        """
        password_hash, salt = self.crypto.hash_password(password)
        sql = ("INSERT INTO users (username, password_hash, salt, display_name) "
               "VALUES (%s, %s, %s, %s)")
        try:
            with self.pool.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, (username, password_hash, salt, display_name))
                    new_id = cur.lastrowid
                conn.commit() if not conn.autocommit else None
            _log.info("创建用户 | id=%d username=%s", new_id, username)
            return int(new_id)
        except _PyMySqlError as e:
            # 1062 = Duplicate entry
            if getattr(e, "args", ()) and "1062" in str(e.args[0] if e.args else ""):
                _log.warning("创建用户失败-用户名已存在 | username=%s", username)
                raise DbError("用户名已存在", code="DB_DUPLICATE_USERNAME")
            _log.error("创建用户失败 | username=%s | %s", username, e)
            raise DbError("创建用户失败: %s" % e, code="DB_INSERT_FAILED")

    def update_last_login(self, user_id: int) -> None:
        sql = "UPDATE users SET last_login_at = NOW() WHERE id = %s"
        with self.pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
            if not conn.autocommit:
                conn.commit()

    def update_password(self, user_id: int, new_password: str) -> None:
        password_hash, salt = self.crypto.hash_password(new_password)
        sql = ("UPDATE users SET password_hash = %s, salt = %s "
               "WHERE id = %s")
        with self.pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (password_hash, salt, user_id))
            if not conn.autocommit:
                conn.commit()


# ============================================================================
#  UserConfigs 数据访问对象
# ============================================================================

class UserConfigsDAO:
    """用户配置 DAO。负责课程 JSON 序列化与配置读写。"""

    def __init__(self, pool: ConnectionPool, crypto: CryptoService):
        self.pool = pool
        self.crypto = crypto

    def _row_to_dict(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """将数据库行转换为 API 返回的字典。"""
        if not row:
            return None
        result = dict(row)
        # 课程 JSON 解析
        cj = result.get("courses_json")
        if isinstance(cj, str):
            try:
                result["courses"] = json.loads(cj)
            except Exception:
                result["courses"] = []
        elif cj is None:
            result["courses"] = []
        else:
            result["courses"] = cj
        result.pop("courses_json", None)
        # 额外配置
        es = result.get("extra_settings")
        if isinstance(es, str):
            try:
                result["extra_settings"] = json.loads(es)
            except Exception:
                result["extra_settings"] = {}
        elif es is None:
            result["extra_settings"] = {}
        # 日期转字符串
        for k in ("semester_start", "created_at", "updated_at"):
            v = result.get(k)
            if v is not None and not isinstance(v, str):
                result[k] = v.strftime("%Y-%m-%d") if k == "semester_start" else v.strftime("%Y-%m-%d %H:%M:%S")
        return result

    def find_by_user_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """返回完整配置。"""
        sql = ("SELECT user_id, "
               "       courses_json, semester_start, total_weeks, "
               "       extra_settings, created_at, updated_at "
               "FROM user_configs WHERE user_id = %s")
        with self.pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
                row = cur.fetchone()
        return self._row_to_dict(row) if row else None

    def find_public_by_user_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """返回配置，适用于前端展示。"""
        return self.find_by_user_id(user_id)

    def upsert(self, user_id: int, data: Dict[str, Any]) -> None:
        """创建或更新用户配置（全字段 upsert）。

        :param user_id: 用户 ID
        :param data:    配置字典，可包含字段：
                        courses, semester_start, total_weeks, extra_settings
        """
        # 课程数据序列化
        courses = data.get("courses")
        if courses is None:
            courses_json = None
        else:
            if not isinstance(courses, list):
                raise DbError("courses 必须是数组", code="DB_INVALID_COURSES")
            courses_json = json.dumps(courses, ensure_ascii=False)
        # 学期配置
        semester_start = data.get("semester_start") or None
        total_weeks = int(data.get("total_weeks") or 18)
        if total_weeks < 1 or total_weeks > 30:
            total_weeks = 18
        # 扩展配置
        extra = data.get("extra_settings")
        if extra is None:
            extra_json = None
        elif isinstance(extra, (dict, list)):
            extra_json = json.dumps(extra, ensure_ascii=False)
        else:
            extra_json = None

        sql = (
            "INSERT INTO user_configs "
            "    (user_id, courses_json, semester_start, total_weeks, extra_settings) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE "
            "    courses_json = IF(VALUES(courses_json) IS NULL, "
            "                      courses_json, VALUES(courses_json)), "
            "    semester_start = VALUES(semester_start), "
            "    total_weeks = VALUES(total_weeks), "
            "    extra_settings = IF(VALUES(extra_settings) IS NULL, "
            "                        extra_settings, VALUES(extra_settings)), "
            "    updated_at = NOW()"
        )
        params = (user_id, courses_json, semester_start, total_weeks, extra_json)
        try:
            with self.pool.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                if not conn.autocommit:
                    conn.commit()
            _log.info("用户配置已保存 | user_id=%d", user_id)
        except _PyMySqlError as e:
            _log.error("保存用户配置失败 | user_id=%d | %s", user_id, e)
            raise DbError("保存用户配置失败: %s" % e, code="DB_UPSERT_FAILED")

    def update_partial(self, user_id: int, data: Dict[str, Any]) -> None:
        """部分更新（只更新 data 中提供的字段，未提供的保留原值）。

        特殊处理：
        - courses: None 时不修改，list 时覆盖
        """
        # 先取当前值
        current = self.find_by_user_id(user_id)
        if current is None:
            # 还没有记录，走完整 upsert
            return self.upsert(user_id, data)

        merged = {
            "semester_start": data.get("semester_start") or current.get("semester_start"),
            "total_weeks": data.get("total_weeks", current.get("total_weeks", 18)),
            "extra_settings": data.get("extra_settings", current.get("extra_settings", {})),
        }
        # courses
        if "courses" in data:
            merged["courses"] = data["courses"]
        return self.upsert(user_id, merged)

    def delete_by_user_id(self, user_id: int) -> None:
        sql = "DELETE FROM user_configs WHERE user_id = %s"
        with self.pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
            if not conn.autocommit:
                conn.commit()


# ============================================================================
#  单例工厂
# ============================================================================

_pool_singleton = None
_pool_lock = threading.Lock()


def get_pool() -> ConnectionPool:
    """获取全局共享的连接池单例。"""
    global _pool_singleton
    if _pool_singleton is None:
        with _pool_lock:
            if _pool_singleton is None:
                _pool_singleton = ConnectionPool(DbConfig())
    return _pool_singleton


def get_users_dao() -> UsersDAO:
    return UsersDAO(get_pool(), get_crypto_service())


def get_user_configs_dao() -> UserConfigsDAO:
    return UserConfigsDAO(get_pool(), get_crypto_service())


def check_connection() -> bool:
    """启动时健康检查：尝试一次简单查询。"""
    try:
        pool = get_pool()
        with pool.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
        return bool(row)
    except Exception:
        return False


# ============================================================================
#  自检
# ============================================================================

if __name__ == "__main__":
    _log.info("DB_DRIVER = %s", _DRIVER or "(未安装)")
    if _DRIVER is None:
        _log.warning("请执行: pip install PyMySQL")
    else:
        ok = check_connection()
        _log.info("数据库连通性: %s", "OK" if ok else "FAILED")
