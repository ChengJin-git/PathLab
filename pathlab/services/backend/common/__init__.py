"""
Common utilities for backend services
"""

from .logger import SimpleLogger, get_logger
from .config import Config, config

__all__ = [
    "SimpleLogger",
    "get_logger",
    "Config",
    "config",
]

