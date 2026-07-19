#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能课程表 Pro — 本地后端（零依赖 · 本地优先）
============================================================
零依赖，仅使用 Python 标准库 (http.server)，本地直接运行。
纯课程表数据服务 + AI 空闲规划代理，无数据库、无第三方依赖。

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

import os

# ----------------------------------------------------------------------------
#  零依赖 .env 加载（不引入 python-dotenv）
#  必须在任何读取 os.environ 的模块导入之前执行，使 .env 中的配置优先生效：
#    - logger 初始化（get_logger）会读 APP_ENV / LOG_* 等环境变量
#    - AI 代理（_handle_ai_plan）会读 TIMETABLE_AI_* 等环境变量
#  规则：仅当该 key 原本不在 os.environ 中时才写入（显式环境变量优先于 .env）。
#  仅当项目根目录存在 .env 文件时才加载，否则静默跳过。
# ----------------------------------------------------------------------------

def _load_dotenv() -> None:
    """读取项目根目录的 .env 并写入 os.environ（不覆盖已有环境变量）。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            # 去掉值两侧引号 " 或 '
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'"):
                value = value[1:-1]
            if key not in os.environ:
                os.environ[key] = value


_load_dotenv()

import json
import re
import sys
import threading
import time
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import socket
import urllib.request
import urllib.error

# 统一日志系统（最早初始化，确保后续模块的日志都能正常输出）
from logger import get_logger, log_context, shutdown_logging, get_manager
log = get_logger("app")

# ---- 基本配置 ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "test_data.js")
HTML_FILE = os.path.join(BASE_DIR, "smart-timetable-pro.html")
HOST = "0.0.0.0"
PORT = 8000

# CORS 受信来源（仅这些来源会收到 Allow-Origin + Allow-Credentials）
_ALLOWED_ORIGINS_RAW = os.environ.get("TIMETABLE_CORS_ORIGIN", "http://localhost:8000")
ALLOWED_ORIGINS = {o.strip() for o in _ALLOWED_ORIGINS_RAW.split(",") if o.strip()}


def _is_local_origin(origin):
    """判断 origin 是否为本地回环（localhost / 127.0.0.1 / ::1 任意端口）。

    用于本地开发时放行：无论用 http://localhost:8000、http://127.0.0.1:8000
    还是 Live Server 等任意本地端口打开前端，调用 /api/* 都不会被 CORS 拦截。
    外部公网站点仍由 ALLOWED_ORIGINS 白名单控制，不在本函数放行范围内。
    """
    try:
        host = urlparse(origin).hostname or ""
    except (ValueError, TypeError):
        return False
    return host in ("localhost", "127.0.0.1", "::1", "[::1]")


# AI 代理限流（模块级锁单飞 + 时间戳令牌桶）
_ai_rate_lock = threading.Lock()
try:
    _ai_min_interval = 1.0 / float(os.environ.get("TIMETABLE_AI_RATE_LIMIT", "1") or "1")
except (ValueError, ZeroDivisionError):
    _ai_min_interval = 1.0
_ai_last_call = 0.0

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
        """CORS 头：对受信来源 / 本地回环来源回显 Origin 并允许凭据；其他来源不写 Allow-Origin。

        受信来源来自 TIMETABLE_CORS_ORIGIN（.env，逗号分隔）；本地回环
        （localhost / 127.0.0.1 / ::1 任意端口）一律放行，便于本地以任意
        http 方式打开前端时调用 /api/* 不被 CORS 拦截。
        避免 `*` 与 `credentials:true` 并存的不规范配置（P1-3）。
        仅对 /api/* 调用；静态文件 _send_file 不调用本方法。
        """
        origin = self.headers.get("Origin")
        if origin and (origin in ALLOWED_ORIGINS or _is_local_origin(origin)):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        # 非法/外部来源：不回显 Allow-Origin（等价于 null），亦不发送 Allow-Credentials
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors()
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
        # 静态资源同源即可，不发送 CORS 头（避免向任意来源泄露）
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
            # ---- AI 空闲规划代理 ----
            if path == "/api/ai/plan":
                self._handle_ai_plan()
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

    # ---- 健康检查 ----
    def _handle_health(self, params):
        """GET /api/health —— 返回服务状态。"""
        self._send_json({
            "ok": True,
            "version": "1.1.0",
        })

    def _handle_ai_plan(self):
        """POST /api/ai/plan — 后端代理式 AI 调用（零三方依赖，使用标准库 urllib.request）。

        接收前端组装好的 messages，原样转发到 {TIMETABLE_AI_BASE_URL}/chat/completions。
        任何异常 / 无 KEY / 限流 / 超时 / 网络中断 / 非 2xx / JSON 解析失败 / choices 为空
        → 统一返回 {ok:false, degraded:true, reason, plan:null}，HTTP 仍为 200。
        成功 → {ok:true, degraded:false, plan:"<content>", model}。
        reason 枚举：AI_DISABLED / AI_RATE_LIMITED / AI_TIMEOUT / AI_NETWORK /
                     AI_HTTP_4XX / AI_HTTP_5XX / AI_UPSTREAM_429 / AI_JSON / AI_EMPTY。
        """
        global _ai_last_call
        api_key = (os.environ.get("TIMETABLE_AI_API_KEY") or "").strip()
        if not api_key:
            self._send_json({"ok": False, "degraded": True, "reason": "AI_DISABLED",
                             "plan": None, "model": None})
            return

        # 限流（模块级锁单飞 + 时间戳令牌桶）
        with _ai_rate_lock:
            now = time.time()
            if now - _ai_last_call < _ai_min_interval:
                self._send_json({"ok": False, "degraded": True, "reason": "AI_RATE_LIMITED",
                                 "plan": None, "model": None})
                return
            _ai_last_call = now

        body = self._read_json_body()
        if body is None:
            self._send_json({"ok": False, "degraded": True, "reason": "AI_JSON",
                             "plan": None, "model": None})
            return

        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            self._send_json({"ok": False, "degraded": True, "reason": "AI_EMPTY",
                             "plan": None, "model": None})
            return

        model = body.get("model") or os.environ.get("TIMETABLE_AI_MODEL", "gpt-4o-mini")
        base_url = (os.environ.get("TIMETABLE_AI_BASE_URL",
                                   "https://api.openai.com/v1") or "https://api.openai.com/v1").rstrip("/")
        try:
            timeout = float(os.environ.get("TIMETABLE_AI_TIMEOUT", "60") or "60")
        except (ValueError, TypeError):
            timeout = 60.0

        try:
            data = json.dumps({"model": model, "messages": messages}, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            self._send_json({"ok": False, "degraded": True, "reason": "AI_JSON",
                             "plan": None, "model": model})
            return

        url = base_url + "/chat/completions"
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + api_key)

        # 后端内部对网络/超时最多重试 1 次（短退避 ~0.3s）；4xx/5xx 不重试
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    status = resp.getcode()
                    raw = resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                status = e.code
                if status == 429:
                    reason = "AI_UPSTREAM_429"
                elif 400 <= status < 500:
                    reason = "AI_HTTP_4XX"
                else:
                    reason = "AI_HTTP_5XX"
                self._send_json({"ok": False, "degraded": True, "reason": reason,
                                 "plan": None, "model": model})
                return
            except (urllib.error.URLError, socket.timeout) as e:
                # 区分超时 vs 其余网络错误：
                #   - socket.timeout 直接抛出，或 URLError.reason 为 socket.timeout 实例 → 超时 → AI_TIMEOUT
                #   - 其余 URLError（DNS 解析失败、连接被拒等）→ 网络中断 → AI_NETWORK
                # 设计契约（INCREMENTAL_DESIGN_AI_PLANNER.md §8）：超时→AI_TIMEOUT；网络中断→AI_NETWORK。
                is_timeout = isinstance(e, socket.timeout) or isinstance(
                    getattr(e, "reason", None), socket.timeout)
                # 仅对「连接类错误」做短退避重试；超时说明上游处理慢，重试大概率仍超时，
                # 不再重试以免双倍等待（如 60s 超时重试会拖到 120s）。
                is_retryable = isinstance(getattr(e, "reason", None), ConnectionError)
                if attempt == 0 and is_retryable:
                    time.sleep(0.3)
                    continue
                self._send_json({
                    "ok": False, "degraded": True,
                    "reason": "AI_TIMEOUT" if is_timeout else "AI_NETWORK",
                    "plan": None, "model": model,
                })
                return
            except Exception:
                self._log.exception("AI plan 调用发生未预期异常")
                self._send_json({"ok": False, "degraded": True, "reason": "AI_NETWORK",
                                 "plan": None, "model": model})
                return

            if status != 200:
                if status == 429:
                    reason = "AI_UPSTREAM_429"
                elif 400 <= status < 500:
                    reason = "AI_HTTP_4XX"
                else:
                    reason = "AI_HTTP_5XX"
                self._send_json({"ok": False, "degraded": True, "reason": reason,
                                 "plan": None, "model": model})
                return

            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                self._send_json({"ok": False, "degraded": True, "reason": "AI_JSON",
                                 "plan": None, "model": model})
                return

            choices = parsed.get("choices") if isinstance(parsed, dict) else None
            if not isinstance(choices, list) or not choices:
                self._send_json({"ok": False, "degraded": True, "reason": "AI_EMPTY",
                                 "plan": None, "model": model})
                return

            msg = (choices[0].get("message") if isinstance(choices[0], dict) else None)
            content = msg.get("content") if isinstance(msg, dict) else None
            if not content or not str(content).strip():
                self._send_json({"ok": False, "degraded": True, "reason": "AI_EMPTY",
                                 "plan": None, "model": model})
                return

            self._send_json({"ok": True, "degraded": False,
                             "plan": str(content), "model": model})
            return

    def do_GET(self):
        rid = self._start_request_context()
        t0 = time.monotonic()
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        self._log.info("GET %s", path)

        try:
            # 1) 健康检查
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
            STATIC_EXTS = {".html", ".js", ".webmanifest", ".svg",
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
        " 智能课程表 Pro — 本地后端 (零依赖 / 本地优先)\n"
        " 数据源: test_data.js (课程) + AI 规划代理\n"
        " 前端:   http://localhost:%d/\n"
        " 接口:   http://localhost:%d/api/courses\n"
        "         http://localhost:%d/api/ai/plan\n"
        "         http://localhost:%d/api/health\n"
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


    # 本地模式（无 MySQL / 无用户配置系统）
    log.info("运行模式 | 本地优先（无 MySQL，用户配置系统已移除）")

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
