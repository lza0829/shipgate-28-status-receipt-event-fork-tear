from __future__ import annotations
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS apps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  owner TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '启用' CHECK(status IN ('启用','停用'))
);
CREATE TABLE IF NOT EXISTS environments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_env_versions (
  app_id INTEGER NOT NULL,
  env_id INTEGER NOT NULL,
  version TEXT NOT NULL DEFAULT '',
  updated_at TEXT,
  PRIMARY KEY(app_id, env_id),
  FOREIGN KEY(app_id) REFERENCES apps(id),
  FOREIGN KEY(env_id) REFERENCES environments(id)
);
CREATE TABLE IF NOT EXISTS releases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  serial TEXT NOT NULL UNIQUE,
  app_id INTEGER NOT NULL,
  target_version TEXT NOT NULL,
  artifact_digest TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '待入闸'
    CHECK(status IN ('待入闸','已入闸','晋升中','已放行','回滚中','已回滚','已关闭')),
  pipeline_status TEXT NOT NULL DEFAULT '未回执'
    CHECK(pipeline_status IN ('未回执','绿','红')),
  current_env_id INTEGER,
  canary_ratio INTEGER NOT NULL DEFAULT 10,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  admitted_at TEXT,
  released_at TEXT,
  rolled_back_at TEXT,
  state_rev INTEGER NOT NULL DEFAULT 0,
  state_advanced_at TEXT,
  FOREIGN KEY(app_id) REFERENCES apps(id),
  FOREIGN KEY(current_env_id) REFERENCES environments(id)
);
CREATE TABLE IF NOT EXISTS promote_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  release_id INTEGER NOT NULL,
  seq INTEGER,
  from_env_id INTEGER,
  to_env_id INTEGER NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('放行','拒绝')),
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  origin TEXT NOT NULL DEFAULT '正常',
  superseded INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(release_id) REFERENCES releases(id),
  FOREIGN KEY(from_env_id) REFERENCES environments(id),
  FOREIGN KEY(to_env_id) REFERENCES environments(id)
);
CREATE TABLE IF NOT EXISTS release_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  env_id INTEGER NOT NULL,
  open_at TEXT NOT NULL,
  close_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '窗开' CHECK(status IN ('窗开','窗关'))
);
CREATE TABLE IF NOT EXISTS rollback_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  env_id INTEGER NOT NULL,
  open_at TEXT NOT NULL,
  close_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '窗开' CHECK(status IN ('窗开','窗关'))
);
CREATE TABLE IF NOT EXISTS instances (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id INTEGER NOT NULL,
  env_id INTEGER NOT NULL,
  version TEXT NOT NULL,
  health TEXT NOT NULL DEFAULT '探针绿' CHECK(health IN ('探针绿','探针红')),
  release_id INTEGER,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(app_id) REFERENCES apps(id),
  FOREIGN KEY(env_id) REFERENCES environments(id),
  FOREIGN KEY(release_id) REFERENCES releases(id)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  ref_id INTEGER,
  action TEXT NOT NULL,
  created_at TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_promote_events_release ON promote_events(release_id, id);
CREATE INDEX IF NOT EXISTS idx_audit_ref ON audit_events(ref_id, id);
CREATE INDEX IF NOT EXISTS idx_audit_kind ON audit_events(kind, id);
"""

# 仅对“有效事件”生效的每单序号唯一索引；作废事件让出序号空间。
SEQ_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_promote_events_valid_seq
ON promote_events(release_id, seq)
WHERE superseded = 0 AND seq IS NOT NULL
"""

# 老库补列（CREATE TABLE IF NOT EXISTS 不会改既有表结构）
MIGRATION_COLUMNS = {
    "releases": {
        "state_rev": "INTEGER NOT NULL DEFAULT 0",
        "state_advanced_at": "TEXT",
    },
    "promote_events": {
        "seq": "INTEGER",
        "origin": "TEXT NOT NULL DEFAULT '正常'",
        "superseded": "INTEGER NOT NULL DEFAULT 0",
    },
}

RELEASE_STATUSES = ("待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭")
PIPELINE_STATUSES = ("未回执", "绿", "红")
HEALTH_STATUSES = ("探针绿", "探针红")
WINDOW_STATUSES = ("窗开", "窗关")


def db_path() -> Path:
    """SHIPGATE_DB 优先，且每次连接都重新读取，便于测试按用例切换库。"""
    return Path(os.environ.get("SHIPGATE_DB", str(DB_PATH)))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # 自动提交模式，事务由 db() 以 BEGIN IMMEDIATE 显式管理
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def db():
    """统一工作单元：BEGIN IMMEDIATE 串行化写者，状态推进与事件写入同笔成败。"""
    ensure_ready()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


_READY_PATHS: set[str] = set()
_READY_LOCK = threading.Lock()


def ensure_ready() -> None:
    """迟设 SHIPGATE_DB 的评测夹具在首次请求时也能拿到建好表、播好种子的库。"""
    key = str(db_path().resolve())
    if key in _READY_PATHS:
        return
    with _READY_LOCK:
        if key in _READY_PATHS:
            return
        from app.seed import seed_if_empty

        seed_if_empty()
        _READY_PATHS.add(key)


def _existing_columns(conn, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db() -> None:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.executescript(SCHEMA)
        for table, columns in MIGRATION_COLUMNS.items():
            present = _existing_columns(conn, table)
            for name, decl in columns.items():
                if name not in present:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        # 老数据回填每单事件序号（按 id 顺序编稠密序号）
        rows = conn.execute(
            """
            SELECT id, release_id FROM promote_events
            WHERE seq IS NULL AND COALESCE(superseded, 0) = 0
            ORDER BY release_id, id
            """
        ).fetchall()
        counters: dict[int, int] = {}
        for row in rows:
            n = counters.get(row["release_id"], 0) + 1
            counters[row["release_id"]] = n
            conn.execute("UPDATE promote_events SET seq=? WHERE id=?", (n, row["id"]))
        conn.execute(SEQ_INDEX_SQL)
        # 老单据补状态推进戳：优先放行/入闸时间，否则用申请时间
        conn.execute(
            """
            UPDATE releases
            SET state_advanced_at = COALESCE(state_advanced_at, released_at, admitted_at, created_at)
            WHERE state_advanced_at IS NULL
            """
        )
        conn.commit()
        _READY_PATHS.add(str(db_path().resolve()))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_list(rows) -> list[dict]:
    return [dict(r) for r in rows]
