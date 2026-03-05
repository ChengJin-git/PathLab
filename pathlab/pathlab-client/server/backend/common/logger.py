"""
Simple unified logger for PathLab

"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_FILE = None


def _ensure_log_file():
    global _LOG_FILE
    if _LOG_FILE is not None:
        return _LOG_FILE
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = open(_LOG_DIR / "pathlab.log", "a", buffering=1)  # line-buffered
    return _LOG_FILE


class SimpleLogger:
    """Simple logger that prints to stdout and logs/pathlab.log"""

    def __init__(self, service_name: str):
        self.service_name = service_name

    def _log(self, level: str, message: str, **kwargs):
        """Internal log method"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        extra = f" | {kwargs}" if kwargs else ""
        line = f"[{timestamp}] [{self.service_name}] [{level}] {message}{extra}"
        print(line, file=sys.stdout)
        try:
            f = _ensure_log_file()
            f.write(line + "\n")
        except Exception:
            pass

    def info(self, message: str, **kwargs):
        """Log info message"""
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self._log("WARN", message, **kwargs)

    def error(self, message: str, **kwargs):
        """Log error message"""
        self._log("ERROR", message, **kwargs)

    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self._log("DEBUG", message, **kwargs)

    def exception(self, message: str, **kwargs):
        """Log error message with traceback"""
        self._log("ERROR", message, **kwargs)
        tb = traceback.format_exc()
        for tbline in tb.splitlines():
            self._log("ERROR", tbline)


# Convenience function to create logger
def get_logger(service_name: str) -> SimpleLogger:
    """Get a logger instance for a service"""
    return SimpleLogger(service_name)

