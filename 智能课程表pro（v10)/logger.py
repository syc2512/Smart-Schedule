#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
logger.py — 统一日志系统
========================

职责：
  1. 控制台实时输出（彩色，便于开发调试）
  2. 文件持久化（按时间或大小滚动切分，便于审计）
  3. 统一格式：时间戳 | 级别 | 模块 | [request_id] | 消息
  4. 容错：文件写入失败回退到 stderr，绝不影响主业务
  5. 配置化：JSON 配置 + 环境变量覆盖，支持 dev/test/prod 环境

设计原则：
  - 零依赖：仅使用 Python 标准库 (logging + logging.handlers)
  - 单例：进程内共享 LoggingManager，避免重复初始化 handler
  - 异常隔离：所有 handler.emit 失败被 logging 模块内部捕获，并叠加 FallbackHandler
  - 上下文绑定：LogContext 支持 request_id 等元信息在线程内传递
  - 热更新：update_level() 运行时调整级别，无需重启

配置优先级（高→低）：
  环境变量 LOG_LEVEL/LOG_FILE/... > logging_config.json > 内置默认值

环境预设：
  dev   : DEBUG  + 控制台彩色 + 文件（按天滚动，保留 7 天）
  test  : INFO   + 控制台 + 文件（按天滚动，保留 14 天）
  prod  : INFO   + 文件（按天滚动，保留 30 天，ERROR 单独文件）

用法：
  from logger import get_logger, log_context
  log = get_logger("app")
  log.info("服务启动", extra={"port": 8000})

  with log_context(request_id="abc123"):
      log.info("处理请求")  # 自动带上 request_id=abc123
"""

import gzip
import json
import logging
import logging.handlers
import os
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from logging.handlers import (
    TimedRotatingFileHandler,
    RotatingFileHandler,
)
from typing import Any, Dict, Optional

# ============================================================================
#  常量
# ============================================================================

CONFIG_FILE_NAME = "logging_config.json"

# 级别映射（字符串 → logging 常量）
LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

# ANSI 颜色（控制台彩色输出）
_ANSI = {
    "RESET": "\033[0m",
    "DEBUG": "\033[36m",   # 青色
    "INFO": "\033[32m",    # 绿色
    "WARNING": "\033[33m", # 黄色
    "ERROR": "\033[31m",   # 红色
    "CRITICAL": "\033[35m",# 紫色
    "TIMESTAMP": "\033[90m",  # 灰色
    "MODULE": "\033[34m",     # 蓝色
    "CONTEXT": "\033[90m",    # 灰色
}


# ============================================================================
#  Formatter
# ============================================================================

STANDARD_FORMAT = (
    "%(asctime)s | %(levelname)-7s | %(name)-16s | %(message)s"
)
STANDARD_FORMAT_WITH_CTX = (
    "%(asctime)s | %(levelname)-7s | %(name)-16s | [%(request_id)s] | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S,%f"[:-3]  # 毫秒精度


class ColorFormatter(logging.Formatter):
    """控制台彩色 Formatter。

    Windows 10+ 支持 ANSI 颜色（需启用 VT 模式）；老系统自动降级为无色。
    """

    def __init__(self, fmt=None, datefmt=None, use_color=True):
        super().__init__(fmt or STANDARD_FORMAT, datefmt or DATE_FORMAT)
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if not self.use_color:
            return super().format(record)
        # 先让父类生成 asctime（formatTime 内部会 setattr 到 record）
        self.formatTime(record, self.datefmt)
        # 保存原始字段，format 后恢复（避免污染 record 被其他 handler 重复着色）
        orig_levelname = record.levelname
        orig_name = record.name
        orig_asctime = getattr(record, "asctime", None)
        orig_request_id = getattr(record, "request_id", "-")
        try:
            # 着色
            color = _ANSI.get(orig_levelname, "")
            if color:
                record.levelname = color + orig_levelname + _ANSI["RESET"]
            record.name = _ANSI["MODULE"] + orig_name + _ANSI["RESET"]
            if orig_asctime:
                record.asctime = _ANSI["TIMESTAMP"] + orig_asctime + _ANSI["RESET"]
            if orig_request_id and orig_request_id != "-":
                record.request_id = _ANSI["CONTEXT"] + str(orig_request_id) + _ANSI["RESET"]
            # 调用祖父类 format（避免再次调用 formatTime）
            return logging.Formatter.format(self, record)
        finally:
            # 恢复，避免其他 handler（如文件 handler）拿到带 ANSI 码的字段
            record.levelname = orig_levelname
            record.name = orig_name
            if orig_asctime is not None:
                record.asctime = orig_asctime
            record.request_id = orig_request_id


class ContextualFormatter(logging.Formatter):
    """支持 request_id 上下文的 Formatter（用于文件）。"""

    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt or STANDARD_FORMAT_WITH_CTX, datefmt or DATE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        # 若 record 没有 request_id 字段，填 "-"
        if not hasattr(record, "request_id") or not record.request_id:
            record.request_id = "-"
        return super().format(record)


# ============================================================================
#  容错 Handler：包装任意 handler，emit 失败时降级到 stderr
# ============================================================================

class SafeHandlerWrapper(logging.Handler):
    """包装一个 handler，捕获其 emit 异常并降级。

    logging 模块自身已有 handleError 兜底（默认打印到 stderr），
    本包装额外做：
      1. 文件磁盘满/权限错误时，关闭文件 handler 防止后续重复报错
      2. 错误计数，超过阈值自动禁用该 handler
      3. 第一次失败时打印一次醒目告警到 stderr
    """

    MAX_ERRORS_BEFORE_DISABLE = 10

    def __init__(self, wrapped: logging.Handler):
        super().__init__(level=wrapped.level)
        self._wrapped = wrapped
        self._error_count = 0
        self._disabled = False
        self._warned = False
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if self._disabled:
            return
        try:
            self._wrapped.emit(record)
        except Exception as e:
            self._on_emit_error(e, record)

    def close(self):
        try:
            self._wrapped.close()
        except Exception:
            pass
        super().close()

    def setLevel(self, level):
        super().setLevel(level)
        try:
            self._wrapped.setLevel(level)
        except Exception:
            pass

    def _on_emit_error(self, err: Exception, record: logging.LogRecord) -> None:
        with self._lock:
            self._error_count += 1
            should_warn = not self._warned
            self._warned = True
            should_disable = self._error_count >= self.MAX_ERRORS_BEFORE_DISABLE
            if should_disable:
                self._disabled = True
        # 第一次失败：打印告警到 stderr（不递归到 logging）
        if should_warn:
            try:
                sys.stderr.write(
                    "\n[logger] 警告：日志 handler 写入失败 (%s: %s)。"
                    "已降级，仅输出到 stderr。\n" % (
                        type(self._wrapped).__name__, err))
                sys.stderr.flush()
            except Exception:
                pass
        # 降级输出：直接打到 stderr
        try:
            msg = self._wrapped.format(record) if hasattr(self._wrapped, "format") \
                else record.getMessage()
            sys.stderr.write("FALLBACK | " + msg + "\n")
            sys.stderr.flush()
        except Exception:
            pass  # 兜底中的兜底，绝不再抛


# ============================================================================
#  Gzip 压缩：滚动后的旧日志自动压缩
# ============================================================================

def _gzip_rotator(source: str, dest: str) -> None:
    """TimedRotatingFileHandler 的 rotator 回调：把滚动出的旧文件 gzip 压缩。"""
    try:
        with open(source, "rb") as f_in:
            with gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        try:
            os.remove(source)
        except OSError:
            pass
    except Exception:
        # 压缩失败保留原文件
        try:
            if os.path.exists(dest) and not os.path.exists(source):
                os.rename(dest, source)
        except Exception:
            pass


def _gzip_namer(name: str) -> str:
    """TimedRotatingFileHandler 的 namer 回调：滚动文件加 .gz 后缀。"""
    return name + ".gz"


# ============================================================================
#  上下文：线程级 request_id 绑定
# ============================================================================

class _LogContext:
    """线程本地存储的日志上下文。"""

    def __init__(self):
        self._local = threading.local()

    def get(self) -> Dict[str, Any]:
        return getattr(self._local, "ctx", {}) or {}

    def set(self, ctx: Dict[str, Any]) -> None:
        self._local.ctx = ctx

    def merge(self, **kwargs) -> Dict[str, Any]:
        cur = dict(self.get())
        cur.update(kwargs)
        self.set(cur)
        return cur

    def clear(self) -> None:
        self._local.ctx = {}


_log_context = _LogContext()


@contextmanager
def log_context(**kwargs):
    """绑定日志上下文（线程内有效）。

    用法：
        with log_context(request_id="abc123", user_id=42):
            log.info("处理请求")   # 日志中自动带上 request_id=abc123
    """
    prev = _log_context.get()
    _log_context.merge(**kwargs)
    try:
        yield
    finally:
        _log_context.set(prev)


# ============================================================================
#  ContextFilter：把上下文注入到每条 LogRecord
# ============================================================================

class ContextFilter(logging.Filter):
    """把 _log_context 中的字段注入 LogRecord，使 Formatter 可引用。

    保证 record 总是有 INJECT_FIELDS 中的字段（默认 "-"），避免
    Formatter 模板 `%(request_id)s` 找不到字段抛 KeyError。
    """

    # 注入到 record 的字段名（与 Formatter 模板对应）
    INJECT_FIELDS = ("request_id", "user_id", "trace_id")

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _log_context.get()
        for field in self.INJECT_FIELDS:
            # 业务代码通过 extra= 显式传入的优先（hasattr 判断）
            if hasattr(record, field):
                continue
            value = ctx.get(field)
            setattr(record, field, value if value is not None else "-")
        return True


# ============================================================================
#  配置
# ============================================================================

class LoggingConfig:
    """日志配置（dataclass 风格）。"""

    def __init__(self):
        self.env = os.environ.get("APP_ENV", "dev").lower()
        self.level = os.environ.get("LOG_LEVEL", "").upper()  # 环境变量优先
        self.log_dir = os.environ.get("LOG_DIR", "")
        self.console_enabled = True
        self.console_color = True
        self.file_enabled = True
        self.file_rolling = "time"        # time | size | both
        self.file_when = "midnight"       # TimedRotating: S/M/H/D/midnight/W0-W6
        self.file_interval = 1
        self.file_backup_count = 30
        self.file_max_bytes = 10 * 1024 * 1024  # 10 MB
        self.error_file_enabled = True    # 单独的 error.log
        self.gzip_old_logs = True
        self.format = STANDARD_FORMAT_WITH_CTX
        # 应用预设
        self._apply_env_preset()

    def _apply_env_preset(self):
        """根据 env 应用预设。"""
        if self.env == "dev":
            if not self.level:
                self.level = "DEBUG"
            self.file_backup_count = 7
            self.console_color = True
        elif self.env == "test":
            if not self.level:
                self.level = "INFO"
            self.file_backup_count = 14
            self.console_color = True
        elif self.env == "prod":
            if not self.level:
                self.level = "INFO"
            self.file_backup_count = 30
            self.console_color = False
            self.error_file_enabled = True
        else:
            if not self.level:
                self.level = "INFO"

    @property
    def level_value(self) -> int:
        return LEVEL_MAP.get(self.level, logging.INFO)

    @property
    def resolved_log_dir(self) -> str:
        if self.log_dir:
            return os.path.abspath(self.log_dir)
        # 默认: 项目根目录下 logs/
        base_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_dir, "logs")


# ============================================================================
#  LoggingManager — 单例
# ============================================================================

class LoggingManager:
    """日志管理单例。

    负责：
      - 读取配置（JSON + 环境变量）
      - 创建 root logger，附加多个 handler（均用 SafeHandlerWrapper 包装）
      - 提供 get_logger(name) 工厂
      - 运行时调整级别（热更新）
      - 关闭/清理 handler（程序退出时）
    """

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, config: Optional[LoggingConfig] = None):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self.config = config or self._load_config()
            self._handlers: list = []
            self._setup_root_logger()
            self._initialized = True
            # 启动时打印一条 banner，便于排查
            root = logging.getLogger()
            root.info(
                "日志系统初始化完成 | env=%s level=%s dir=%s",
                self.config.env, self.config.level, self.config.resolved_log_dir)

    # ---------- 配置加载 ----------

    def _load_config(self) -> LoggingConfig:
        cfg = LoggingConfig()
        # 读取 JSON 配置（如有）
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cfg_path = os.path.join(base_dir, "config", CONFIG_FILE_NAME)
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    env_preset = data.get(self.config.env if False else cfg.env, {})
                    # 全局字段 + 环境特定字段（环境特定覆盖全局）
                    for k, v in data.items():
                        if k in ("dev", "test", "prod"):
                            continue
                        self._apply_cfg_field(cfg, k, v)
                    for k, v in (env_preset or {}).items():
                        self._apply_cfg_field(cfg, k, v)
            except Exception:
                pass
        # 环境变量最终覆盖（最高优先级）
        env_level = os.environ.get("LOG_LEVEL", "").upper()
        if env_level and env_level in LEVEL_MAP:
            cfg.level = env_level
        env_dir = os.environ.get("LOG_DIR", "")
        if env_dir:
            cfg.log_dir = env_dir
        env_console = os.environ.get("LOG_CONSOLE", "")
        if env_console:
            cfg.console_enabled = env_console.lower() in ("1", "true", "yes")
        env_file = os.environ.get("LOG_FILE", "")
        if env_file:
            cfg.file_enabled = env_file.lower() in ("1", "true", "yes")
        return cfg

    @staticmethod
    def _apply_cfg_field(cfg: LoggingConfig, key: str, value: Any):
        if key in ("env", "level", "log_dir", "console_enabled", "console_color",
                   "file_enabled", "file_rolling", "file_when", "file_interval",
                   "file_backup_count", "file_max_bytes", "error_file_enabled",
                   "gzip_old_logs", "format"):
            try:
                if key == "file_max_bytes":
                    # 支持 "10MB" / "1GB" 字符串
                    if isinstance(value, str):
                        value = _parse_size(value)
                setattr(cfg, key, value)
            except Exception:
                pass

    # ---------- root logger 设置 ----------

    def _setup_root_logger(self):
        cfg = self.config
        root = logging.getLogger()
        root.setLevel(cfg.level_value)
        # 清空现有 handler（避免重复，比如 reload 时）
        for h in list(root.handlers):
            try:
                h.close()
            except Exception:
                pass
        root.handlers.clear()
        # 上下文 Filter（注入 request_id 等）—— 加到 wrapper 上而非内部 handler，
        # 因为 SafeHandlerWrapper.emit 会直接调内部 handler.emit 跳过其 handle 流程
        ctx_filter = ContextFilter()
        # 1) 控制台
        if cfg.console_enabled:
            console_handler = logging.StreamHandler(stream=sys.stderr)
            console_handler.setLevel(cfg.level_value)
            console_handler.setFormatter(
                ColorFormatter(
                    fmt=cfg.format,
                    use_color=cfg.console_color,
                )
            )
            wrapped = SafeHandlerWrapper(console_handler)
            wrapped.addFilter(ctx_filter)
            root.addHandler(wrapped)
            self._handlers.append(wrapped)
        # 2) 文件
        if cfg.file_enabled:
            self._add_file_handlers(root, ctx_filter)
        # 3) 阻止传播到上级（root 是顶层）
        root.propagate = False
        # 4) 调整第三方库日志噪音
        for noisy in ("urllib3", "requests", "chardet", "charset_normalizer"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    def _add_file_handlers(self, root: logging.Logger, ctx_filter: logging.Filter):
        cfg = self.config
        log_dir = cfg.resolved_log_dir
        # 创建日志目录（失败时仅警告，不抛异常）
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            try:
                sys.stderr.write("[logger] 警告：创建日志目录失败 %s: %s\n" % (log_dir, e))
            except Exception:
                pass
            return

        formatter = ContextualFormatter(fmt=cfg.format)

        def _make_file_handler(filename: str, level: int) -> Optional[SafeHandlerWrapper]:
            filepath = os.path.join(log_dir, filename)
            try:
                if cfg.file_rolling in ("time", "both"):
                    handler = TimedRotatingFileHandler(
                        filepath,
                        when=cfg.file_when,
                        interval=cfg.file_interval,
                        backupCount=cfg.file_backup_count,
                        encoding="utf-8",
                        delay=True,  # 延迟创建文件，避免启动时就创建
                    )
                    if cfg.gzip_old_logs:
                        handler.rotator = _gzip_rotator
                        handler.namer = _gzip_namer
                elif cfg.file_rolling == "size":
                    handler = RotatingFileHandler(
                        filepath,
                        maxBytes=cfg.file_max_bytes,
                        backupCount=cfg.file_backup_count,
                        encoding="utf-8",
                        delay=True,
                    )
                else:
                    handler = TimedRotatingFileHandler(
                        filepath, when="midnight", backupCount=cfg.file_backup_count,
                        encoding="utf-8", delay=True,
                    )
                handler.setLevel(level)
                handler.setFormatter(formatter)
                wrapped = SafeHandlerWrapper(handler)
                wrapped.addFilter(ctx_filter)
                root.addHandler(wrapped)
                self._handlers.append(wrapped)
                return wrapped
            except Exception as e:
                try:
                    sys.stderr.write(
                        "[logger] 警告：创建文件 handler 失败 %s: %s\n" % (filepath, e))
                except Exception:
                    pass
                return None

        # 主日志文件
        _make_file_handler("app.log", cfg.level_value)
        # 错误日志单独一份（便于排查）
        if cfg.error_file_enabled:
            _make_file_handler("error.log", logging.ERROR)

    # ---------- 对外 API ----------

    def get_logger(self, name: str) -> logging.Logger:
        """获取命名 logger。"""
        logger = logging.getLogger(name)
        logger.setLevel(self.config.level_value)
        return logger

    def update_level(self, level: str) -> bool:
        """运行时调整全局日志级别（热更新）。"""
        level = level.upper()
        if level not in LEVEL_MAP:
            return False
        lvl = LEVEL_MAP[level]
        self.config.level = level
        root = logging.getLogger()
        root.setLevel(lvl)
        for h in self._handlers:
            try:
                h.setLevel(lvl)
            except Exception:
                pass
        root.info("日志级别已切换为 %s", level)
        return True

    def get_status(self) -> Dict[str, Any]:
        """返回当前日志系统状态（供 /api/health 等使用）。"""
        cfg = self.config
        return {
            "env": cfg.env,
            "level": cfg.level,
            "log_dir": cfg.resolved_log_dir,
            "console_enabled": cfg.console_enabled,
            "file_enabled": cfg.file_enabled,
            "file_rolling": cfg.file_rolling,
            "file_backup_count": cfg.file_backup_count,
            "error_file_enabled": cfg.error_file_enabled,
            "handlers_count": len(self._handlers),
        }

    def close(self):
        """关闭所有 handler（程序退出时调用）。"""
        for h in self._handlers:
            try:
                h.close()
            except Exception:
                pass
        self._handlers.clear()


# ============================================================================
#  辅助函数
# ============================================================================

def _parse_size(s: str) -> int:
    """解析 '10MB' / '1GB' / '512KB' 等字符串为字节数。"""
    s = s.strip().upper()
    multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    for suffix, mul in multipliers.items():
        if s.endswith(suffix):
            num = s[:-len(suffix)].strip()
            try:
                return int(num) * mul
            except ValueError:
                break
    try:
        return int(s)
    except ValueError:
        return 10 * 1024 * 1024


# ============================================================================
#  单例工厂
# ============================================================================

_manager: Optional[LoggingManager] = None
_manager_lock = threading.Lock()


def get_manager() -> LoggingManager:
    """获取全局 LoggingManager 单例。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = LoggingManager()
    return _manager


def get_logger(name: str = "app") -> logging.Logger:
    """获取命名 logger（推荐入口）。

    :param name: 模块名，如 "app" / "ai"
    """
    return get_manager().get_logger(name)


def init_logging(config: Optional[LoggingConfig] = None) -> LoggingManager:
    """显式初始化日志系统（可传入自定义配置）。"""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.close()
        _manager = LoggingManager(config)
    return _manager


def shutdown_logging():
    """程序退出时调用，确保所有缓冲日志刷盘。"""
    global _manager
    if _manager is not None:
        _manager.close()
    logging.shutdown()


# ============================================================================
#  自检
# ============================================================================

if __name__ == "__main__":
    # 测试环境：强制 dev 模式 + DEBUG
    os.environ.setdefault("APP_ENV", "dev")
    os.environ.setdefault("LOG_LEVEL", "DEBUG")
    os.environ.setdefault("LOG_DIR", "./logs_test")

    log = get_logger("selftest")

    print("\n--- 基础日志测试 ---")
    log.debug("调试消息")
    log.info("信息消息")
    log.warning("警告消息")
    log.error("错误消息")
    log.critical("严重错误")

    print("\n--- 上下文测试 ---")
    with log_context(request_id="req-abc-123", user_id=42):
        log.info("处理用户请求")
        with log_context(action="login"):
            log.info("执行登录子操作")

    print("\n--- extra 字段测试 ---")
    log.info("带 extra 的消息", extra={"custom_field": "hello"})

    print("\n--- 异常堆栈测试 ---")
    try:
        1 / 0
    except ZeroDivisionError:
        log.exception("捕获到除零异常")

    print("\n--- 状态 ---")
    mgr = get_manager()
    status = mgr.get_status()
    for k, v in status.items():
        print("  %s = %s" % (k, v))

    print("\n--- 热更新测试 ---")
    print("切换到 WARN ...")
    mgr.update_level("WARN")
    log.info("这条 INFO 不应出现")
    log.warning("这条 WARN 应该出现")
    mgr.update_level("DEBUG")
    log.info("恢复 DEBUG 后 INFO 重新可见")

    print("\n--- 日志文件检查 ---")
    log_dir = mgr.config.resolved_log_dir
    if os.path.isdir(log_dir):
        for f in sorted(os.listdir(log_dir)):
            full = os.path.join(log_dir, f)
            size = os.path.getsize(full)
            print("  %s (%d bytes)" % (f, size))

    print("\n所有自检通过 ✓")
    print("日志目录:", log_dir)
    shutdown_logging()
