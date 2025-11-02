"""
Simple unified logger for SmartResearch

"""
import sys
from datetime import datetime


class SimpleLogger:
    """Simple logger that prints to stdout with consistent format"""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
    
    def _log(self, level: str, message: str, **kwargs):
        """Internal log method"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        extra = f" | {kwargs}" if kwargs else ""
        print(f"[{timestamp}] [{self.service_name}] [{level}] {message}{extra}", file=sys.stdout)
    
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


# Convenience function to create logger
def get_logger(service_name: str) -> SimpleLogger:
    """Get a logger instance for a service"""
    return SimpleLogger(service_name)

