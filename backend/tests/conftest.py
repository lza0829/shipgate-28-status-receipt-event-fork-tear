from __future__ import annotations

import os
import sys
import tempfile
import sqlite3
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_TMP = tempfile.mkdtemp(prefix="shipgate-pytest-")
os.environ.setdefault("SHIPGATE_DB", str(Path(_TMP) / "shipgate.db"))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import db, db_path, init_db  # noqa: E402
from app.main import app  # noqa: E402

_ALL_TABLES = [
    "audit_events",
    "settings",
    "instances",
    "rollback_windows",
    "release_windows",
    "promote_events",
    "releases",
    "app_env_versions",
    "apps",
    "environments",
]


@pytest.fixture(scope="session", autouse=True)
def _schema_once():
    init_db()
    yield


def reset_database() -> None:
    with db() as conn:
        # 顺序：子表先于父表，满足外键约束
        for table in _ALL_TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")
    from app.seed import seed_if_empty

    seed_if_empty()


@pytest.fixture()
def client():
    """每个用例一份全新种子数据（表结构只建一次）。"""
    reset_database()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_file():
    return str(db_path())


@pytest.fixture()
def raw(db_file):
    """直连 SQLite 注入夹具（缺事件/手改状态/半截拧花）。"""
    conns: list[sqlite3.Connection] = []

    def _open() -> sqlite3.Connection:
        conn = sqlite3.connect(db_file, timeout=30)
        conn.row_factory = sqlite3.Row
        conns.append(conn)
        return conn

    yield _open
    for conn in conns:
        try:
            conn.close()
        except sqlite3.Error:
            pass


def promote_to(client, rid, env):
    return client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": env})


def seed_release_id(client) -> int:
    rows = client.get("/api/发版单").json()
    return rows[0]["编号"]
