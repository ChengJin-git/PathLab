"""Patch-level classifiers package.

Add new classifiers by implementing BaseClassifier and registering in registry.py.
"""
from .registry import get_classifier, list_classifiers, register_classifier

__all__ = [
    "get_classifier",
    "list_classifiers",
    "register_classifier",
]

