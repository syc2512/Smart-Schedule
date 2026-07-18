#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
llm_client.py — 云端大模型调用客户端（韧性 SDK 封装）
=====================================================

设计目标（对应需求）：
  1. 密钥管理  : API Key 从环境变量 / .env 自动读取，绝不硬编码到源码。
  2. 超时处理  : 每次请求设置独立超时，避免长时间阻塞。
  3. 自动重试  : 可配置重试次数与间隔（指数退避 + 抖动），仅对可重试错误重试。
  4. 熔断机制  : 连续失败达到阈值后熔断（OPEN），冷却后进入半开探测（HALF_OPEN），
                成功则自动恢复（CLOSED）。
  5. 限流控制  : 令牌桶限流，防止超出云端 API 配额。
  6. 日志埋点  : 关键链路记录 请求参数 / 响应摘要 / 耗时 / 异常，并对密钥脱敏。

架构（传输无关，便于扩展）：
  ResilientLLMClient
      ├─ RateLimiter       (令牌桶，限制调用频率)
      ├─ CircuitBreaker    (closed / open / half-open 状态机)
      ├─ RetryPolicy       (指数退避 + 抖动)
      └─ Transport         (实际 HTTP 传输)
            ├─ OpenAITransport   (openai Python SDK，优先)
            ├─ UrllibTransport   (标准库 urllib，零依赖回退)
            └─ MockTransport     (不联网，用于链路/逻辑验证)

配置优先级：环境变量 / .env  >  llm_config.json  >  内置默认值。

依赖：
  - 主传输使用 openai Python SDK（pip install openai），未安装时自动回退到
    标准库 urllib，保证项目零依赖也可运行。
  - .env 读取使用标准库实现，无需 python-dotenv。

用法：
  from llm_client import get_llm_client, LlmError

  client = get_llm_client()                       # 依据 llm_config.json + .env 构建
  content = client.chat("把这段课表文本解析成 JSON",
                        system_prompt="你是课程表解析助手...")
"""

import json
import logging
import os
import random
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

try:
    import urllib.error
    import urllib.request
except Exception:  # pragma: no cover
    urllib = None

try:
    import openai  # 优先使用官方 SDK；未安装时为 None
except Exception:
    openai = None


# ============================================================================
#  常量
# ============================================================================

# 可重试的错误码（配合状态码进一步判断）
RETRYABLE_CODES = {"LLM_TIMEOUT", "LLM_CONNECT_ERROR", "LLM_HTTP_ERROR"}

DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
CONFIG_FILE_NAME = "llm_config.json"


# ============================================================================
#  业务异常（带错误码，供上层映射 HTTP 状态）
# ============================================================================

class LlmError(Exception):
    """大模型调用相关异常，携带机器可读的错误码。"""

    def __init__(self, message, code, status_code=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code

    def __str__(self):
        return "[%s] %s" % (self.code, self.message)


class CircuitOpenError(LlmError):
    """熔断开启时直接失败，不发起请求。"""

    def __init__(self, message="大模型服务熔断中，暂时拒绝请求，恢复后将自动重连"):
        super().__init__(message, "LLM_CIRCUIT_OPEN", status_code=503)


class RateLimitError(LlmError):
    """触发本地限流，超出调用配额。"""

    def __init__(self, message="触发本地限流，调用频率超过配置上限"):
        super().__init__(message, "LLM_RATE_LIMITED", status_code=429)


# ============================================================================
#  配置（dataclass，可配置、易扩展）
# ============================================================================

@dataclass
class RetryConfig:
    max_attempts: int = 3          # 含首次，最多尝试次数
    backoff_base: float = 1.0       # 基础退避（秒）
    backoff_factor: float = 2.0     # 指数因子
    backoff_max: float = 10.0       # 单次退避上限（秒）
    jitter: float = 0.2             # 抖动比例（0~1）


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5      # 连续失败达到该值即熔断
    cooldown_seconds: float = 30.0  # 熔断后冷却时长
    half_open_max_calls: int = 1    # 半开状态允许的探测调用数


@dataclass
class RateLimitConfig:
    max_calls: int = 10             # 时间窗口内允许的最大调用数
    window_seconds: float = 1.0     # 时间窗口（秒）
    max_wait_seconds: float = 5.0   # 获取令牌的最大等待（超时则抛限流异常）


@dataclass
class LoggingConfig:
    level: str = "INFO"             # 日志级别
    mask_key: bool = True           # 是否对 api_key 脱敏
    truncate_text: int = 200        # 请求/响应文本截断长度（字符）


@dataclass
class LLMConfig:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 30.0
    mock: bool = False
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    @property
    def host(self) -> str:
        try:
            from urllib.parse import urlparse
            return urlparse(self.base_url).netloc or self.base_url
        except Exception:
            return self.base_url


# ============================================================================
#  .env / 环境变量加载（标准库实现，零依赖）
# ============================================================================

def _load_dotenv(path: str) -> None:
    """极简 .env 解析：KEY=VALUE，支持 # 注释与首尾空格，不覆盖已存在的环境变量。"""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                # 去除引号
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        # .env 是可选增强，解析失败不应阻塞主流程
        pass


def load_config(config_path: Optional[str] = None) -> LLMConfig:
    """加载配置：.env → 环境变量 → llm_config.json → 默认值。

    优先级：环境变量(LLM_*) 最高，其次配置文件，最后内置默认。
    敏感信息（api_key）只从环境变量/.env 或配置文件读取，绝不出现在代码中。
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 1) 加载 .env（若存在）
    _load_dotenv(os.path.join(base_dir, ".env"))

    cfg = LLMConfig()

    # 2) 配置文件（llm_config.json）：提供 base_url / model / timeout / mock / 韧性参数
    if config_path is None:
        config_path = os.path.join(base_dir, CONFIG_FILE_NAME)
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
            if isinstance(file_cfg, dict):
                if file_cfg.get("base_url"):
                    cfg.base_url = file_cfg["base_url"]
                if file_cfg.get("model"):
                    cfg.model = file_cfg["model"]
                if isinstance(file_cfg.get("timeout"), (int, float)):
                    cfg.timeout = float(file_cfg["timeout"])
                if isinstance(file_cfg.get("mock"), bool):
                    cfg.mock = file_cfg["mock"]
                # 韧性配置段
                _apply_subconfig(file_cfg.get("retry"), cfg.retry, RetryConfig)
                _apply_subconfig(file_cfg.get("circuit_breaker"),
                                 cfg.circuit_breaker, CircuitBreakerConfig)
                _apply_subconfig(file_cfg.get("rate_limit"),
                                 cfg.rate_limit, RateLimitConfig)
                _apply_subconfig(file_cfg.get("logging"), cfg.logging, LoggingConfig)
        except Exception:
            # 配置文件损坏不致命，使用默认值
            pass

    # 3) 环境变量覆盖（最高优先级），api_key 也必须走这里
    if os.environ.get("LLM_API_KEY"):
        cfg.api_key = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_BASE_URL"):
        cfg.base_url = os.environ["LLM_BASE_URL"]
    if os.environ.get("LLM_MODEL"):
        cfg.model = os.environ["LLM_MODEL"]
    if os.environ.get("LLM_TIMEOUT"):
        try:
            cfg.timeout = float(os.environ["LLM_TIMEOUT"])
        except ValueError:
            pass
    if os.environ.get("LLM_MOCK"):
        cfg.mock = os.environ["LLM_MOCK"].lower() in ("1", "true", "yes")

    # 防御：api_key 来自配置文件但为空字符串 -> 视为未配置
    if not cfg.has_api_key and not cfg.mock:
        # 允许从配置文件读取 api_key（向后兼容），但默认推荐放 .env
        if isinstance(file_cfg, dict) and file_cfg.get("api_key"):
            cfg.api_key = file_cfg["api_key"]

    return cfg


def _apply_subconfig(src, target, cls):
    """把配置文件中的子字典合并到 dataclass 实例。"""
    if not isinstance(src, dict):
        return
    for k, v in src.items():
        if hasattr(target, k) and v is not None:
            try:
                setattr(target, k, v)
            except Exception:
                pass


# ============================================================================
#  限流：令牌桶（线程安全）
# ============================================================================

class RateLimiter:
    """令牌桶限流器。

    - 每 window_seconds 补充 max_calls 个令牌；
    - acquire() 阻塞等待直到拿到令牌或超时（max_wait_seconds）；
    - 超时抛出 RateLimitError。
    """

    def __init__(self, cfg: RateLimitConfig):
        self.capacity = max(1, int(cfg.max_calls))
        self.window = max(0.05, float(cfg.window_seconds))
        self.max_wait = float(cfg.max_wait_seconds)
        self._tokens = float(self.capacity)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: Optional[float] = None) -> None:
        deadline = time.monotonic() + (self.max_wait if timeout is None else timeout)
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._updated
                if elapsed >= self.window:
                    self._tokens = float(self.capacity)
                    self._updated = now
                elif elapsed > 0:
                    self._tokens = min(
                        float(self.capacity),
                        self._tokens + elapsed / self.window * self.capacity)
                    self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            if time.monotonic() >= deadline:
                raise RateLimitError()
            time.sleep(min(0.05, deadline - time.monotonic()))

    @property
    def available(self) -> float:
        with self._lock:
            return self._tokens


# ============================================================================
#  熔断：closed / open / half-open 状态机（线程安全）
# ============================================================================

class CircuitBreaker:
    """连续失败达到阈值即熔断；冷却后进入半开探测；探测成功则恢复。"""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self, cfg: CircuitBreakerConfig, logger=None):
        self.failure_threshold = max(1, int(cfg.failure_threshold))
        self.cooldown = float(cfg.cooldown_seconds)
        self.half_open_max = max(1, int(cfg.half_open_max_calls))
        self._logger = logger
        self._failures = 0
        self._state = self.CLOSED
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    # -- 状态查询 --
    def allow(self) -> bool:
        with self._lock:
            if self._state == self.CLOSED:
                return True
            if self._state == self.OPEN:
                if time.monotonic() - self._opened_at >= self.cooldown:
                    self._state = self.HALF_OPEN
                    self._half_open_calls = 0
                    self._log("circuit_half_open")
                    return True
                return False
            # HALF_OPEN
            return self._half_open_calls < self.half_open_max

    # -- 结果上报 --
    def on_failure(self) -> None:
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._open()
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open()

    def on_success(self) -> None:
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._state = self.CLOSED
                self._failures = 0
                self._half_open_calls = 0
                self._log("circuit_closed")
                return
            self._failures = 0

    def _open(self) -> None:
        if self._state != self.OPEN:
            self._state = self.OPEN
            self._opened_at = time.monotonic()
            self._log("circuit_open")

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def _log(self, event):
        if self._logger:
            self._logger(logging.INFO, event, state=self._state)


# ============================================================================
#  传输层（Transport）：实际发起 HTTP 请求
# ============================================================================

class BaseTransport:
    """传输层接口：输入参数，返回助手消息文本内容字符串。失败时抛 LlmError。"""

    def complete(self, *, model, system_prompt, user_text,
                 temperature, timeout) -> str:
        raise NotImplementedError


class MockTransport(BaseTransport):
    """Mock 传输：不联网，返回固定 JSON，用于验证全链路与韧性逻辑。"""

    def complete(self, *, model, system_prompt, user_text,
                 temperature, timeout) -> str:
        return json.dumps([
            {"name": "示例课程(Mock)", "teacher": "AI助手", "location": "在线",
             "weekday": 1, "startPeriod": 1, "endPeriod": 2,
             "weekType": "all", "colorIndex": 0},
            {"name": "解析流程演示", "teacher": "测试", "location": "本地",
             "weekday": 3, "startPeriod": 5, "endPeriod": 6,
             "weekType": "odd", "colorIndex": 5},
        ], ensure_ascii=False)


class UrllibTransport(BaseTransport):
    """标准库 urllib 传输（零依赖回退方案）。"""

    def __init__(self, api_key, base_url):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def complete(self, *, model, system_prompt, user_text,
                 temperature, timeout) -> str:
        if not self.api_key:
            raise LlmError("未配置大模型 API Key",
                           "LLM_NOT_CONFIGURED", status_code=503)
        url = self.base_url + "/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": temperature,
            "stream": False,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "Bearer " + self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except socket.timeout:
            raise LlmError("大模型请求超时（%d 秒）" % int(timeout),
                           "LLM_TIMEOUT", status_code=504)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:300]
            except Exception:
                pass
            raise LlmError("大模型返回 HTTP %d：%s" % (e.code, detail),
                           "LLM_HTTP_ERROR", status_code=e.code)
        except urllib.error.URLError as e:
            raise LlmError("无法连接大模型服务：%s" % getattr(e, "reason", e),
                           "LLM_CONNECT_ERROR", status_code=502)
        except LlmError:
            raise
        except Exception as e:
            raise LlmError("大模型请求异常：%s" % e,
                           "LLM_ERROR", status_code=502)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LlmError("大模型返回格式异常，未找到回复内容",
                           "LLM_BAD_RESPONSE", status_code=502)


class OpenAITransport(BaseTransport):
    """openai Python SDK 传输（优先方案，需 pip install openai）。"""

    def __init__(self, api_key, base_url, timeout):
        if openai is None:
            raise ImportError("未安装 openai SDK，请执行 pip install openai，"
                              "或移除依赖以使用标准库 urllib 回退。")
        if not api_key:
            raise LlmError("未配置大模型 API Key",
                           "LLM_NOT_CONFIGURED", status_code=503)
        # max_retries=0：重试由本客户端统一控制，避免双重重试
        self._client = openai.OpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)

    def complete(self, *, model, system_prompt, user_text,
                 temperature, timeout) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                temperature=temperature,
                stream=False,
                timeout=timeout,
            )
            return resp.choices[0].message.content
        except LlmError:
            raise
        except Exception as e:  # 映射到统一错误
            status = getattr(e, "status_code", None)
            if status == 429:
                raise LlmError("大模型返回 429（限流）", "LLM_HTTP_ERROR",
                               status_code=429)
            if "timeout" in type(e).__name__.lower():
                raise LlmError("大模型请求超时", "LLM_TIMEOUT", status_code=504)
            if "connection" in type(e).__name__.lower():
                raise LlmError("无法连接大模型服务：%s" % e,
                               "LLM_CONNECT_ERROR", status_code=502)
            if status is not None:
                raise LlmError("大模型返回 HTTP %d：%s" % (status, e),
                               "LLM_HTTP_ERROR", status_code=status)
            raise LlmError("大模型请求异常：%s" % e, "LLM_ERROR", status_code=502)


def build_transport(cfg: LLMConfig) -> BaseTransport:
    """根据配置选择传输实现。"""
    if cfg.mock:
        return MockTransport()
    # 优先 openai SDK，未安装则回退 urllib
    try:
        return OpenAITransport(cfg.api_key, cfg.base_url, cfg.timeout)
    except ImportError:
        if urllib is None:
            raise LlmError("标准库 urllib 不可用且未安装 openai SDK",
                           "LLM_NOT_CONFIGURED", status_code=503)
        return UrllibTransport(cfg.api_key, cfg.base_url)


# ============================================================================
#  日志埋点（结构化、密钥脱敏）
# ============================================================================

class CallLogger:
    """在关键链路输出结构化日志：请求参数 / 响应摘要 / 耗时 / 异常。"""

    def __init__(self, cfg: LoggingConfig):
        self.cfg = cfg
        self.logger = logging.getLogger("llm_client")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter(
                "[%(asctime)s] %(levelname)s %(message)s"))
            self.logger.addHandler(handler)
        try:
            self.logger.setLevel(getattr(logging, cfg.level.upper(), logging.INFO))
        except Exception:
            self.logger.setLevel(logging.INFO)

    def _mask(self, key: str) -> str:
        if self.cfg.mask_key and key:
            if len(key) <= 8:
                return "****"
            return key[:4] + "..." + key[-4:]
        return key

    def _truncate(self, text) -> str:
        if not isinstance(text, str):
            text = str(text)
        n = self.cfg.truncate_text
        return text if len(text) <= n else text[:n] + "...(truncated)"

    def emit(self, level, event, **fields):
        if "api_key" in fields:
            fields["api_key"] = self._mask(fields["api_key"])
        if "user_text" in fields:
            fields["user_text"] = self._truncate(fields["user_text"])
        if "response" in fields:
            fields["response"] = self._truncate(fields["response"])
        msg = "%s %s" % (event, json.dumps(fields, ensure_ascii=False, default=str))
        self.logger.log(level, msg)


# ============================================================================
#  韧性客户端：组装 限流 + 熔断 + 重试 + 传输 + 日志
# ============================================================================

class ResilientLLMClient:
    """对云端大模型的韧性调用客户端。"""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self.transport = build_transport(cfg)
        self.rate_limiter = RateLimiter(cfg.rate_limit)
        self.log = CallLogger(cfg.logging)
        # 把熔断器的状态日志接到 CallLogger
        self.breaker = CircuitBreaker(cfg.circuit_breaker, logger=self.log.emit)

    # -- 对外接口 --
    def chat(self, user_text, system_prompt="", temperature=0.0,
             timeout=None) -> str:
        """发起一次对话补全，返回助手消息内容字符串。失败抛 LlmError。"""
        req_id = uuid.uuid4().hex[:12]
        timeout = self.cfg.timeout if timeout is None else timeout
        t0 = time.monotonic()

        self.log.emit(logging.INFO, "llm_call_start",
                      request_id=req_id, model=self.cfg.model,
                      host=self.cfg.host, api_key=self.cfg.api_key,
                      timeout=timeout,
                      user_text=user_text,
                      circuit_state=self.breaker.state)

        last_err = None
        for attempt in range(1, self.cfg.retry.max_attempts + 1):
            # 1) 熔断检查（每次尝试前都检查，捕获重试期间被打开的熔断）
            if not self.breaker.allow():
                err = CircuitOpenError()
                self._log_failure(req_id, attempt, err, t0)
                raise err

            # 2) 限流（令牌桶，超时抛限流异常）
            try:
                self.rate_limiter.acquire()
            except RateLimitError as e:
                self.log.emit(logging.WARNING, "llm_rate_limited",
                              request_id=req_id, available=self.rate_limiter.available)
                self._log_failure(req_id, attempt, e, t0)
                raise

            # 3) 发起请求
            try:
                content = self.transport.complete(
                    model=self.cfg.model, system_prompt=system_prompt,
                    user_text=user_text, temperature=temperature, timeout=timeout)
                self.breaker.on_success()
                latency = (time.monotonic() - t0) * 1000
                self.log.emit(logging.INFO, "llm_call_success",
                              request_id=req_id, attempt=attempt,
                              latency_ms=round(latency, 2),
                              response=content,
                              circuit_state=self.breaker.state)
                return content
            except LlmError as e:
                self.breaker.on_failure()
                last_err = e
                retryable = self._is_retryable(e)
                self.log.emit(
                    logging.WARNING if retryable else logging.ERROR,
                    "llm_call_error",
                    request_id=req_id, attempt=attempt,
                    code=e.code, status_code=e.status_code,
                    retryable=retryable, error=str(e),
                    circuit_state=self.breaker.state)
                if not retryable or attempt == self.cfg.retry.max_attempts:
                    self._log_failure(req_id, attempt, e, t0)
                    raise
                # 退避后重试
                delay = self._backoff(attempt)
                self.log.emit(logging.INFO, "llm_retry_wait",
                              request_id=req_id, attempt=attempt,
                              delay_sec=round(delay, 3))
                time.sleep(delay)

        # 理论不会到达；保险起见
        if last_err:
            self._log_failure(req_id, self.cfg.retry.max_attempts, last_err, t0)
            raise last_err
        raise LlmError("未知错误", "LLM_ERROR", status_code=502)

    # -- 内部工具 --
    def _is_retryable(self, err: LlmError) -> bool:
        if err.code not in RETRYABLE_CODES:
            return False
        if err.code == "LLM_HTTP_ERROR":
            sc = err.status_code
            # 5xx 与 429 可重试；其它 4xx 不重试
            return sc is None or sc >= 500 or sc == 429
        return True

    def _backoff(self, attempt: int) -> float:
        r = self.cfg.retry
        delay = min(r.backoff_max, r.backoff_base * (r.backoff_factor ** (attempt - 1)))
        if r.jitter > 0:
            delay += random.uniform(0, r.jitter) * delay
        return max(0.0, delay)

    def _log_failure(self, req_id, attempt, err, t0):
        latency = (time.monotonic() - t0) * 1000
        self.log.emit(logging.ERROR, "llm_call_failed",
                      request_id=req_id, attempt=attempt,
                      code=err.code, status_code=err.status_code,
                      latency_ms=round(latency, 2), error=str(err),
                      circuit_state=self.breaker.state)


# ============================================================================
#  便捷单例：供 app.py 等直接使用
# ============================================================================

_client_cache = {"client": None, "cfg": None}
_cache_lock = threading.Lock()


def get_llm_client() -> ResilientLLMClient:
    """返回进程内共享的客户端（依据当前配置构建一次）。"""
    with _cache_lock:
        if _client_cache["client"] is None:
            cfg = load_config()
            _client_cache["client"] = ResilientLLMClient(cfg)
            _client_cache["cfg"] = cfg
        return _client_cache["client"]


def reset_client() -> None:
    """重置缓存（测试或配置热更新时使用）。"""
    with _cache_lock:
        _client_cache["client"] = None
        _client_cache["cfg"] = None


if __name__ == "__main__":
    # 简单自检：mock 模式跑通一次
    os.environ.setdefault("LLM_MOCK", "true")
    c = get_llm_client()
    print(c.chat("测试文本", system_prompt="你是助手"))
    print("circuit_state =", c.breaker.state)
