"""Database connection helpers using psycopg2 connection pool."""

import logging
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

_pool: pool.SimpleConnectionPool | None = None


def get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
    return _pool


@contextmanager
def get_conn():
    """Yield a connection from the pool; auto-return on exit."""
    p = get_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)


@contextmanager
def get_cursor(*, dict_cursor: bool = True):
    """Yield a cursor (RealDictCursor by default) that auto-commits."""
    cursor_factory = RealDictCursor if dict_cursor else None
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=cursor_factory)
        try:
            yield cur
        finally:
            cur.close()


def execute(sql: str, params: tuple | None = None) -> None:
    with get_cursor(dict_cursor=False) as cur:
        cur.execute(sql, params)


def fetch_all(sql: str, params: tuple | None = None) -> list[dict]:
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql: str, params: tuple | None = None) -> dict | None:
    with get_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def upsert_cost(date_val, **kwargs):
    """Upsert a row into cost_tracking for the given date."""
    cols = list(kwargs.keys())
    placeholders = ", ".join(f"%({c})s" for c in cols)
    updates = ", ".join(f"{c} = cost_tracking.{c} + EXCLUDED.{c}" for c in cols)
    col_names = ", ".join(cols)
    sql = f"""
        INSERT INTO cost_tracking (date, {col_names})
        VALUES (%(date)s, {placeholders})
        ON CONFLICT (date) DO UPDATE SET {updates},
            total_cost_usd = cost_tracking.apify_cost_usd + cost_tracking.llm_cost_usd + cost_tracking.proxy_cost_usd
    """
    kwargs["date"] = date_val
    execute(sql, kwargs)
