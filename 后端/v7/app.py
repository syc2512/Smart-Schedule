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
  2. POST /api/ai/parse
       接收 {text: "..."}（用户粘贴的课程文本），服务端组装结构化
       Prompt 调用免费大模型（OpenAI 兼容），把返回结果包装成与
       test_data.js 完全一致的 8 字段课程数组后返回。
       失败/超时返回明确错误 JSON {error, code}。配置见 llm_config.json。
  3. GET /                  返回前端页面 smart-timetable-pro.html
  4. GET /<静态资源>         返回同目录前端文件
       (timetable-data.js / manifest.webmanifest / icon.svg 等)

数据源：直接读取同目录 test_data.js，不使用数据库。
启动： python app.py    然后浏览器访问 http://localhost:8000/
"""

import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

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
#  LLM 网关：POST /api/ai/parse
#  接收用户文本 → 组装 Prompt → 调用 OpenAI 兼容免费大模型
#  → 包装为与 test_data.js 一致的课程结构 → 返回
# ============================================================

LLM_CONFIG_FILE = os.path.join(BASE_DIR, "llm_config.json")

# 课程字段约束（与 timetable-data.js / test_data.js 完全一致）
MAX_PERIOD = 12          # timeSlots 共 12 节
NUM_COLORS = 12          # colorPalette 共 12 色（索引 0-11）
VALID_WEEKTYPES = ("all", "odd", "even")

# 解析提示词（镜像自 timetable-data.js 的 ai.prompts.parseText，保证一致）
PARSE_SYSTEM_PROMPT = (
    "你是课程表解析助手。从文本中提取课程，返回 JSON 数组。"
    "每门课程字段：name(课程名),teacher(教师),location(地点),"
    "weekday(1-7,周一至周日),startPeriod(起始节次1-12),"
    "endPeriod(结束节次1-12),weekType('all'|'odd'|'even'),"
    "colorIndex(0-11,可空)。仅返回 JSON，不要解释。"
)


class LlmError(Exception):
    """大模型调用相关的业务异常，带错误码。"""

    def __init__(self, message, code):
        super(LlmError, self).__init__(message)
        self.message = message
        self.code = code


def load_llm_config():
    """读取 LLM 配置：环境变量优先，其次 llm_config.json，最后内置默认值。"""
    cfg = {
        "api_key": "",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "timeout": 30,
        "mock": False,
    }
    # 配置文件
    if os.path.isfile(LLM_CONFIG_FILE):
        try:
            with open(LLM_CONFIG_FILE, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            if isinstance(file_cfg, dict):
                for k, v in file_cfg.items():
                    if v != "" or k == "api_key":
                        cfg[k] = v
        except Exception:
            pass
    # 环境变量覆盖
    if os.environ.get("LLM_API_KEY"):
        cfg["api_key"] = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_BASE_URL"):
        cfg["base_url"] = os.environ["LLM_BASE_URL"]
    if os.environ.get("LLM_MODEL"):
        cfg["model"] = os.environ["LLM_MODEL"]
    return cfg


def _clamp_int(v, lo, hi, default=None):
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = lo if default is None else default
    return max(lo, min(hi, v))


def wrap_courses(raw):
    """将 LLM 返回的原始对象列表规范化为标准课程结构（8 字段）。

    与前端 normalizeAI() 逻辑一致，保证客户端可直接解析渲染。
    字段：name/teacher/location/weekday/startPeriod/endPeriod/weekType/colorIndex
    """
    out = []
    if not isinstance(raw, list):
        return out
    for r in raw:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", "")).strip()
        if not name:
            continue  # 丢弃无名的非法项
        sp = _clamp_int(r.get("startPeriod", 1), 1, MAX_PERIOD, 1)
        ep = _clamp_int(r.get("endPeriod", sp), 1, MAX_PERIOD, sp)
        if ep < sp:
            ep = sp
        wt = r.get("weekType", "all")
        if wt not in VALID_WEEKTYPES:
            wt = "all"
        ci = _clamp_int(r.get("colorIndex", 0), 0, NUM_COLORS - 1, 0) % NUM_COLORS
        out.append({
            "name": name,
            "teacher": str(r.get("teacher", "")).strip(),
            "location": str(r.get("location", "")).strip(),
            "weekday": _clamp_int(r.get("weekday", 1), 1, 7, 1),
            "startPeriod": sp,
            "endPeriod": ep,
            "weekType": wt,
            "colorIndex": ci,
        })
    return out


def extract_json_array(content):
    """从大模型文本回复中提取 JSON 数组（兼容 ```json``` 代码块包裹）。"""
    if not content:
        return []
    text = content if isinstance(content, str) else str(content)
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1)
    # 提取第一个 [...] 块
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
        return arr if isinstance(arr, list) else []
    except json.JSONDecodeError:
        return []


def _mock_llm_content(user_text):
    """Mock 模式：不调用真实大模型，返回固定 JSON，用于验证全链路打通。"""
    return json.dumps([
        {"name": "示例课程(Mock)", "teacher": "AI助手", "location": "在线",
         "weekday": 1, "startPeriod": 1, "endPeriod": 2,
         "weekType": "all", "colorIndex": 0},
        {"name": "解析流程演示", "teacher": "测试", "location": "本地",
         "weekday": 3, "startPeriod": 5, "endPeriod": 6,
         "weekType": "odd", "colorIndex": 5},
    ], ensure_ascii=False)


def call_llm(user_text, cfg):
    """调用 OpenAI 兼容的 /chat/completions，返回内容字符串。失败抛 LlmError。"""
    # Mock 模式：跳过真实请求，便于无 Key 时验证客户端↔服务端链路
    if cfg.get("mock"):
        return _mock_llm_content(user_text)

    if not cfg.get("api_key"):
        raise LlmError(
            "未配置大模型 API Key，请在 llm_config.json 中填写 api_key"
            "（或将 mock 设为 true 进行链路测试）", "LLM_NOT_CONFIGURED")

    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + cfg["api_key"])
    timeout = cfg.get("timeout", 30)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except socket.timeout:
        raise LlmError("大模型请求超时（%d 秒）" % timeout, "LLM_TIMEOUT")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        raise LlmError("大模型返回 HTTP %d：%s" % (e.code, detail), "LLM_HTTP_ERROR")
    except urllib.error.URLError as e:
        raise LlmError("无法连接大模型服务：%s" % getattr(e, "reason", e),
                       "LLM_CONNECT_ERROR")
    except LlmError:
        raise
    except Exception as e:
        raise LlmError("大模型请求异常：%s" % e, "LLM_ERROR")

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LlmError("大模型返回格式异常，未找到回复内容", "LLM_BAD_RESPONSE")


class Handler(BaseHTTPRequestHandler):
    server_version = "STP-Local/1.0"

    # ---- 工具方法 ----
    def _add_cors(self):
        """统一 CORS 头，允许前端从任意来源访问（本地开发用）。"""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/ai/parse":
                self._handle_ai_parse()
                return
            self._send_json({"error": "Not Found", "path": path}, status=404)
        except Exception as e:
            self._send_json(
                {"error": "Internal Server Error", "detail": str(e)}, status=500)

    def _handle_ai_parse(self):
        """POST /api/ai/parse —— 用户文本 → 大模型 → 包装为课程数组。"""
        body = self._read_json_body()
        if body is None:
            self._send_json({"error": "请求体不是合法 JSON", "code": "BAD_JSON"},
                            status=400)
            return
        text = (body.get("text") or "").strip() if isinstance(body, dict) else ""
        if not text:
            self._send_json({"error": "缺少 text 字段或内容为空", "code": "EMPTY_TEXT"},
                            status=400)
            return

        cfg = load_llm_config()
        try:
            content = call_llm(text, cfg)
        except LlmError as e:
            # 未配置 Key 视为服务端不可用(503)；其余大模型错误为网关错误(502)
            status = 503 if e.code == "LLM_NOT_CONFIGURED" else 502
            sys.stderr.write("[AI parse error] %s: %s\n" % (e.code, e.message))
            self._send_json({"error": e.message, "code": e.code}, status=status)
            return

        raw_list = extract_json_array(content)
        courses = wrap_courses(raw_list)
        self._send_json(courses)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            # 1) 课程数据接口
            if path == "/api/courses":
                courses = parse_mock_courses()
                courses = filter_courses(courses, params)
                self._send_json(courses)
                return

            # 2) 首页
            if path == "/" or path == "/index.html":
                if os.path.isfile(HTML_FILE):
                    self._send_file(HTML_FILE)
                else:
                    self._send_json({"error": "前端页面不存在"}, status=404)
                return

            # 3) 静态资源（扩展名白名单 + 路径穿越防护，避免泄露 .py 等源码）
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

            # 4) 404
            self._send_json({"error": "Not Found", "path": path}, status=404)

        except FileNotFoundError as e:
            self._send_json({"error": "数据文件缺失", "detail": str(e)}, status=500)
        except Exception as e:
            self._send_json(
                {"error": "Internal Server Error", "detail": str(e)}, status=500)

    def log_message(self, fmt, *args):
        """简洁访问日志。"""
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    banner = (
        "=" * 58 + "\n"
        " 智能课程表 Pro — 本地后端 (方案 A)\n"
        " 数据源: test_data.js (无数据库)\n"
        " 前端:   http://localhost:%d/\n"
        " 接口:   http://localhost:%d/api/courses\n"
        "         http://localhost:%d/api/ai/parse (大模型解析)\n"
        + "=" * 58
    ) % (PORT, PORT, PORT)
    print(banner)

    # 启动时预校验数据文件可解析
    try:
        courses = parse_mock_courses()
        print(" 已加载 %d 门课程" % len(courses))
    except Exception as e:
        print(" [警告] 数据加载失败: %s" % e)

    # 打印 LLM 配置状态
    cfg = load_llm_config()
    if cfg.get("mock"):
        print(" 大模型: MOCK 模式（不调用真实 API，用于链路测试）")
    elif cfg.get("api_key"):
        print(" 大模型: %s @ %s" % (cfg.get("model"), cfg.get("base_url")))
    else:
        print(" 大模型: 未配置 API Key（/api/ai/parse 将返回 503；"
              "请填写 llm_config.json 或设 mock=true 测试）")
    print("")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n收到中断，正在停止...")
        server.shutdown()
        print("已停止。")


if __name__ == "__main__":
    main()
