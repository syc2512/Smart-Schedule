#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能课程表 Pro — 本地后端 (方案 A：本地优先 + 轻量数据服务)
============================================================
零依赖，仅使用 Python 标准库 (http.server)，本地直接运行。

功能：
  1. GET /api/courses
       返回 test_data.js 中的 mockCourses 列表（JSON 数组）。
       支持可选查询参数（按需过滤，不传则返回全部）：
         ?weekday=1            按星期过滤（1-7）
         ?weekType=odd         按周次过滤（all / odd / even）
         ?name=高  或 ?q=高    按课程名模糊匹配
     返回格式与前端 normalize() 期望一致，前端可直接解析展示。
  2. GET /                  返回前端页面 smart-timetable-pro.html
  3. GET /<静态资源>         返回同目录前端文件
       (timetable-data.js / manifest.webmanifest / icon.svg 等)

数据源：直接读取同目录 test_data.js，不使用数据库。
启动： python app.py    然后浏览器访问 http://localhost:8000/
"""

import json
import os
import re
import sys
import time
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 统一日志系统（最早初始化，确保后续模块的日志都能正常输出）
from logger import get_logger, log_context, shutdown_logging, get_manager
log = get_logger("app")


# 用户配置管理系统（鉴权 + 数据库 + 加密）
from auth import AuthService, AuthError, get_auth_service, SESSION_COOKIE_NAME
from db import DbError, get_users_dao, get_user_configs_dao, check_connection

# 标记用户配置管理模块是否可用（缺少 MySQL 驱动时降级到原零依赖模式）
try:
    _USER_CONFIG_ENABLED = check_connection()
except Exception as e:
    log.warning("MySQL 连接检查失败，用户配置管理将降级: %s", e)
    _USER_CONFIG_ENABLED = False

# ---- 基本配置 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "test_data.js")
HTML_FILE = os.path.join(BASE_DIR, "smart-timetable-pro.html")
HOST = "0.0.0.0"
PORT = 8000

# 静态资源 MIME 映射
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".css": "text/css; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

# 课程数据缓存：(文件 mtime, 解析结果)，文件变更时自动重读
_course_cache = {"mtime": None, "data": None}


def parse_mock_courses():
    """从 test_data.js 中提取 mockCourses 数组。

    test_data.js 是 JS 文件，但 mockCourses 数组部分是合法 JSON
    （双引号键/值、无尾逗号、无行内注释），用平衡括号匹配提取后
    直接 json.loads。
    """
    if not os.path.isfile(DATA_FILE):
        raise FileNotFoundError("数据文件不存在: test_data.js")

    mtime = os.path.getmtime(DATA_FILE)
    if _course_cache["data"] is not None and _course_cache["mtime"] == mtime:
        return _course_cache["data"]

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        text = f.read()

    # 定位 "mockCourses = ["
    m = re.search(r"mockCourses\s*=\s*\[", text)
    if not m:
        raise RuntimeError("test_data.js 中未找到 mockCourses 数组定义")

    start = m.end() - 1  # 指向 '['
    depth = 0
    in_str = False
    str_ch = ""
    end = None
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == str_ch:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                str_ch = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        i += 1

    if end is None:
        raise RuntimeError("mockCourses 数组括号未闭合")

    arr_str = text[start:end + 1]
    try:
        courses = json.loads(arr_str)
    except json.JSONDecodeError as e:
        raise RuntimeError("mockCourses 数组 JSON 解析失败: %s" % e)

    if not isinstance(courses, list):
        raise RuntimeError("mockCourses 不是数组")

    _course_cache["mtime"] = mtime
    _course_cache["data"] = courses
    return courses


def filter_courses(courses, params):
    """根据可选查询参数过滤课程。"""
    out = courses

    # weekday：按星期过滤
    if "weekday" in params:
        try:
            wd = int(params["weekday"][0])
            out = [c for c in out if c.get("weekday") == wd]
        except (ValueError, IndexError):
            pass

    # weekType：按周次过滤（all / odd / even）
    if "weekType" in params:
        try:
            wt = params["weekType"][0]
            out = [c for c in out if c.get("weekType") == wt]
        except IndexError:
            pass

    # name 或 q：课程名模糊匹配
    q = None
    if "name" in params:
        q = params["name"][0]
    elif "q" in params:
        q = params["q"][0]
    if q:
        out = [c for c in out if q in c.get("name", "")]

    return out


# ============================================================










class Handler(BaseHTTPRequestHandler):
    server_version = "STP-Local/1.0"

    # 模块级 logger（实例共享）
    _log = log

    def _new_request_id(self) -> str:
        """为每个请求生成唯一 ID（用于日志关联）。"""
        return uuid.uuid4().hex[:12]

    def _start_request_context(self):
        """绑定 request_id 到当前线程的日志上下文。"""
        rid = self._new_request_id()
        self._request_id = rid
        log_context(request_id=rid)
        return rid

    def _end_request_context(self):
        """清理请求上下文。"""
        try:
            log_context(request_id="-")
        except Exception:
            pass    # ---- 工具方法 ----
    def _add_cors(self):
        """统一 CORS 头，允许前端从任意来源访问（本地开发用）。"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Credentials", "true")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json_with_cookie(self, data, set_cookie_value, status=200):
        """下发 JSON 同时附带 Set-Cookie 头（用于登录/注册/登出）。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", set_cookie_value)
        self._add_cors()
        # 允许携带 Cookie（与 SameSite=Strict 配合，开发模式仍可用）
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._add_cors()
        self.end_headers()
        self.wfile.write(body)

    # ---- HTTP 方法 ----
    def do_OPTIONS(self):
        """预检请求。"""
        self.send_response(204)
        self._add_cors()
        self.end_headers()

    def _read_json_body(self):
        """读取并解析 POST 请求体为 dict；非法 JSON 返回 None。"""
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            obj = json.loads(raw.decode("utf-8"))
            return obj if isinstance(obj, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_POST(self):
        rid = self._start_request_context()
        t0 = time.monotonic()
        parsed = urlparse(self.path)
        path = parsed.path
        self._log.info("POST %s", path)
        try:
            # ---- 用户配置管理 API ----
            if path == "/api/auth/register":
                self._handle_register()
                return
            if path == "/api/auth/login":
                self._handle_login()
                return
            if path == "/api/auth/logout":
                self._handle_logout()
                return
            if path == "/api/user/config":
                self._handle_save_user_config()
                return
            if path == "/api/user/courses":
                self._handle_save_user_courses()
                return

            self._send_json({"error": "Not Found", "path": path}, status=404)
        except Exception as e:
            self._log.exception("POST %s 处理异常", path)
            self._send_json(
                {"error": "Internal Server Error", "detail": str(e)}, status=500)
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._log.info("POST %s 完成 | %dms", path, round(elapsed_ms, 1))
            self._end_request_context()

    # ============================================================
    #  用户配置管理 API
    # ============================================================

    def _check_user_config_enabled(self):
        """检查用户配置管理模块是否可用（MySQL 已连接）。"""
        if not _USER_CONFIG_ENABLED:
            self._send_json({
                "error": "用户配置管理未启用（MySQL 不可用，请检查 DB 配置）",
                "code": "USER_CONFIG_DISABLED"
            }, status=503)
            return False
        return True

    def _get_current_user_id(self):
        """从 Cookie 中提取并校验 Session，返回 (user_id, error_response)。

        若未登录，返回 (None, None) —— 调用方决定如何响应。
        若 Session 无效，返回 (None, error_dict)。
        """
        cookie_header = self.headers.get("Cookie")
        ticket = AuthService.extract_ticket_from_cookie(cookie_header)
        auth = get_auth_service()
        user_id = auth.verify_session(ticket)
        return user_id

    def _require_auth(self):
        """要求登录才能访问。成功返回 user_id，失败直接发送 401 并返回 None。"""
        user_id = self._get_current_user_id()
        if user_id is None:
            self._send_json({
                "error": "未登录或 Session 已过期",
                "code": "AUTH_REQUIRED"
            }, status=401)
            return None
        return user_id

    # ---- 注册 ----
    def _handle_register(self):
        """POST /api/auth/register
        Body: {"username": "...", "password": "...", "display_name": "..."}
        """
        if not self._check_user_config_enabled():
            return
        body = self._read_json_body()
        if body is None:
            self._send_json({"error": "请求体不是合法 JSON", "code": "BAD_JSON"}, status=400)
            return
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        display_name = (body.get("display_name") or "").strip() or None

        auth = get_auth_service()
        try:
            result = auth.register(username, password, display_name)
        except AuthError as e:
            status = 409 if e.code == "AUTH_USERNAME_TAKEN" else 400
            self._send_json({"error": e.message, "code": e.code}, status=status)
            return
        except DbError as e:
            self._send_json({"error": e.message, "code": e.code}, status=500)
            return

        cookie_val = AuthService.build_set_cookie_header(result.session_ticket, result.expires_in)
        self._send_json_with_cookie({
            "user": {
                "id": result.user_id,
                "username": result.username,
                "display_name": result.display_name,
            },
            "expires_in": result.expires_in,
        }, cookie_val, status=201)

    # ---- 登录 ----
    def _handle_login(self):
        """POST /api/auth/login
        Body: {"username": "...", "password": "..."}
        """
        if not self._check_user_config_enabled():
            return
        body = self._read_json_body()
        if body is None:
            self._send_json({"error": "请求体不是合法 JSON", "code": "BAD_JSON"}, status=400)
            return
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""

        auth = get_auth_service()
        try:
            result = auth.authenticate(username, password)
        except AuthError as e:
            status = 401 if e.code in ("AUTH_INVALID_CREDENTIALS",
                                        "AUTH_ACCOUNT_DISABLED") else 400
            self._send_json({"error": e.message, "code": e.code}, status=status)
            return
        except DbError as e:
            self._send_json({"error": e.message, "code": e.code}, status=500)
            return

        # 登录后取用户信息（用于前端展示）
        user_info = auth.get_user_info(result.user_id) or {}
        cookie_val = AuthService.build_set_cookie_header(result.session_ticket, result.expires_in)
        self._send_json_with_cookie({
            "user": user_info,
            "expires_in": result.expires_in,
        }, cookie_val)

    # ---- 登出 ----
    def _handle_logout(self):
        """POST /api/auth/logout —— 清除 Cookie。"""
        cookie_val = AuthService.build_clear_cookie_header()
        self._send_json_with_cookie({"ok": True}, cookie_val)

    # ---- 当前用户信息 ----
    def _handle_me(self):
        """GET /api/auth/me —— 返回当前登录用户信息。"""
        if not self._check_user_config_enabled():
            return
        user_id = self._require_auth()
        if user_id is None:
            return
        auth = get_auth_service()
        info = auth.get_user_info(user_id)
        if info is None:
            self._send_json({"error": "用户不存在", "code": "USER_NOT_FOUND"}, status=404)
            return
        configs_dao = get_user_configs_dao()
        cfg = configs_dao.find_public_by_user_id(user_id)
        info["has_config"] = cfg is not None
        self._send_json({"user": info})

    # ---- 获取用户配置 ----
    def _handle_get_user_config(self):
        """GET /api/user/config —— 返回当前用户的配置（不含 API_KEY 明文）。"""
        if not self._check_user_config_enabled():
            return
        user_id = self._require_auth()
        if user_id is None:
            return
        try:
            configs_dao = get_user_configs_dao()
            cfg = configs_dao.find_public_by_user_id(user_id)
            if cfg is None:
                # 首次登录：返回空配置，前端引导填写
                self._send_json({
                    "config": None,
                    "first_login": True,
                    "message": "首次登录，请填写配置"
                })
                return
            self._send_json({"config": cfg, "first_login": False})
        except DbError as e:
            self._send_json({"error": e.message, "code": e.code}, status=500)

    # ---- 保存 / 更新用户配置 ----
    def _handle_save_user_config(self):
        """POST /api/user/config —— 创建或更新用户配置（全字段或部分字段）。

        Body: {
            "semester_start": "2025-09-01",
            "total_weeks": 18,
            "extra_settings": {...}
        }
        """
        if not self._check_user_config_enabled():
            return
        user_id = self._require_auth()
        if user_id is None:
            return
        body = self._read_json_body()
        if body is None:
            self._send_json({"error": "请求体不是合法 JSON", "code": "BAD_JSON"}, status=400)
            return

        # 字段白名单 + 长度校验
        allowed = {"semester_start", "total_weeks", "extra_settings"}
        data = {k: v for k, v in body.items() if k in allowed}
        if "total_weeks" in data:
            try:
                tw = int(data["total_weeks"])
                if tw < 1 or tw > 30:
                    raise ValueError()
                data["total_weeks"] = tw
            except (ValueError, TypeError):
                self._send_json({"error": "total_weeks 必须是 1-30 的整数",
                                 "code": "VALIDATION_ERROR"}, status=400)
                return
        if "semester_start" in data and data["semester_start"]:
            # 校验日期格式 YYYY-MM-DD
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(data["semester_start"])):
                self._send_json({"error": "semester_start 必须是 YYYY-MM-DD 格式",
                                 "code": "VALIDATION_ERROR"}, status=400)
                return

        try:
            configs_dao = get_user_configs_dao()
            configs_dao.update_partial(user_id, data)
            # 返回更新后的配置
            updated = configs_dao.find_public_by_user_id(user_id)
            self._send_json({"ok": True, "config": updated})
        except DbError as e:
            self._send_json({"error": e.message, "code": e.code}, status=500)
        except Exception as e:
            self._send_json({"error": "保存失败: %s" % e, "code": "SAVE_FAILED"}, status=500)

    # ---- 获取用户课程 ----
    def _handle_get_user_courses(self):
        """GET /api/user/courses —— 返回当前用户存储的课程数据。"""
        if not self._check_user_config_enabled():
            return
        user_id = self._require_auth()
        if user_id is None:
            return
        try:
            configs_dao = get_user_configs_dao()
            cfg = configs_dao.find_by_user_id(user_id)
            courses = (cfg or {}).get("courses", []) or []
            self._send_json({"courses": courses})
        except DbError as e:
            self._send_json({"error": e.message, "code": e.code}, status=500)

    # ---- 保存用户课程 ----
    def _handle_save_user_courses(self):
        """POST /api/user/courses —— 保存用户的课程数据（覆盖式）。

        Body: {"courses": [...]}
        """
        if not self._check_user_config_enabled():
            return
        user_id = self._require_auth()
        if user_id is None:
            return
        body = self._read_json_body()
        if body is None:
            self._send_json({"error": "请求体不是合法 JSON", "code": "BAD_JSON"}, status=400)
            return
        courses = body.get("courses")
        if not isinstance(courses, list):
            self._send_json({"error": "courses 必须是数组", "code": "VALIDATION_ERROR"}, status=400)
            return
        # 限制单用户课程数量，防滥用
        if len(courses) > 500:
            self._send_json({"error": "课程数量超过上限（500）",
                             "code": "VALIDATION_ERROR"}, status=400)
            return

        try:
            configs_dao = get_user_configs_dao()
            configs_dao.update_partial(user_id, {"courses": courses})
            self._send_json({"ok": True, "count": len(courses)})
        except DbError as e:
            self._send_json({"error": e.message, "code": e.code}, status=500)

    # ---- 健康检查 ----
    def _handle_health(self, params):
        """GET /api/health —— 返回服务与依赖状态。"""
        try:
            db_ok = _USER_CONFIG_ENABLED
        except Exception:
            db_ok = False
        self._send_json({
            "ok": True,
            "user_config_enabled": db_ok,
            "version": "1.1.0",
        })

    def do_GET(self):
        rid = self._start_request_context()
        t0 = time.monotonic()
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        self._log.info("GET %s", path)

        try:
            # 1) 用户配置管理 API
            if path == "/api/auth/me":
                self._handle_me()
                return
            if path == "/api/user/config":
                self._handle_get_user_config()
                return
            if path == "/api/user/courses":
                self._handle_get_user_courses()
                return
            if path == "/api/health":
                self._handle_health(params)
                return

            # 2) 课程数据接口
            if path == "/api/courses":
                courses = parse_mock_courses()
                courses = filter_courses(courses, params)
                self._send_json(courses)
                return

            # 3) 首页
            if path == "/" or path == "/index.html":
                if os.path.isfile(HTML_FILE):
                    self._send_file(HTML_FILE)
                else:
                    self._send_json({"error": "前端页面不存在"}, status=404)
                return

            # 4) 静态资源（扩展名白名单 + 路径穿越防护，避免泄露 .py 等源码）
            STATIC_EXTS = {".html", ".js", ".json", ".webmanifest", ".svg",
                           ".png", ".jpg", ".ico", ".css", ".txt"}
            rel = path.lstrip("/")
            if rel and ".." not in rel.split("/"):
                target = os.path.normpath(os.path.join(BASE_DIR, rel))
                ext = os.path.splitext(target)[1].lower()
                if (ext in STATIC_EXTS
                        and os.path.isfile(target)
                        and os.path.abspath(target).startswith(BASE_DIR + os.sep)):
                    self._send_file(target)
                    return

            # 5) 404
            self._send_json({"error": "Not Found", "path": path}, status=404)

        except FileNotFoundError as e:
            self._log.error("数据文件缺失: %s", e)
            self._send_json({"error": "数据文件缺失", "detail": str(e)}, status=500)
        except Exception as e:
            self._log.exception("GET %s 处理异常", path)
            self._send_json(
                {"error": "Internal Server Error", "detail": str(e)}, status=500)
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self._log.info("GET %s 完成 | %dms", path, round(elapsed_ms, 1))
            self._end_request_context()

    def log_message(self, fmt, *args):
        """覆盖默认 BaseHTTPRequestHandler 日志，改用统一 logger。"""
        try:
            self._log.debug("HTTP %s - %s", self.address_string(), fmt % args)
        except Exception:
            pass


def main():
    banner = (
        "=" * 58 + "\n"
        " 智能课程表 Pro — 本地后端 (方案 A + 用户配置管理)\n"
        " 数据源: test_data.js (默认) + MySQL (用户配置)\n"
        " 前端:   http://localhost:%d/\n"
        " 接口:   http://localhost:%d/api/courses\n"
        "         http://localhost:%d/api/auth/register|login|logout|me\n"
        "         http://localhost:%d/api/user/config | /api/user/courses\n"
        " 日志:   %s\n"
        + "=" * 58
    ) % (PORT, PORT, PORT, PORT, get_manager().config.resolved_log_dir)
    print(banner)
    log.info("=" * 30 + " 服务启动 " + "=" * 30)

    # 启动时预校验数据文件可解析
    try:
        courses = parse_mock_courses()
        log.info("数据加载 | test_data.js | %d 门课程", len(courses))
    except Exception as e:
        log.warning("数据加载失败 | %s", e)


    # 打印用户配置管理模块状态
    if _USER_CONFIG_ENABLED:
        log.info("用户配置管理 | 已启用 (MySQL 已连接)")
    else:
        log.warning("用户配置管理 | 未启用 (MySQL 不可用，原功能降级可用)")

    # 打印日志系统状态
    log_status = get_manager().get_status()
    log.info("日志系统 | env=%s level=%s handlers=%d",
             log_status["env"], log_status["level"], log_status["handlers_count"])

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("HTTP 服务监听 | %s:%d", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("收到中断信号，正在停止服务...")
        server.shutdown()
        log.info("服务已停止")
        shutdown_logging()


if __name__ == "__main__":
    main()
