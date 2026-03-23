"""Shared query utility helpers for all Repository classes."""

from __future__ import annotations
from typing import Optional, Any
from sqlalchemy import asc, desc
from sqlalchemy.sql import Select


def paginate_query(
    query: Select,
    skip: int = 0,
    limit: int = 0,
    order_by: Optional[Any] = None,
    descending: bool = True,
) -> Select:
    """Apply offset/limit pagination and optional ordering to a SELECT query."""
    if order_by is not None:
        query = query.order_by(desc(order_by) if descending else asc(order_by))
    query = query.offset(skip)
    if limit > 0:
        query = query.limit(limit)
    return query


def apply_user_filter(
    query: Select, model_class: Any, user_id: Optional[str]
) -> Select:
    """Conditionally filter query by user_id when a value is provided."""
    if user_id is not None:
        query = query.where(model_class.user_id == user_id)
    return query
