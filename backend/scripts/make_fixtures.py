"""构造晋升真源四类夹具库：晋升后对账、事件缺失、事件越位、半截单态/名册拧花。

用法：
    SHIPGATE_DB=/tmp/fixture.db python3 scripts/make_fixtures.py
    SHIPGATE_DB=/tmp/fixture.db uvicorn app.main:app --port 11800

然后访问 /对账 查看差额，并可用 POST /api/对账/纠偏 一键收敛。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# 允许通过第一个位置参数直接给库路径
if len(sys.argv) > 1:
    os.environ["SHIPGATE_DB"] = sys.argv[1]

import sqlite3  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.db import db_path, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402


def build() -> None:
    path = db_path()
    if path.exists():
        path.unlink()
    init_db()
    seed_if_empty()

    c = TestClient(app)

    def make_release(name: str, version: str = "1.4.0") -> int:
        aid = c.post("/api/应用", json={"名称": name}).json()["编号"]
        rid = c.post(
            "/api/发版单",
            json={"应用编号": aid, "目标版本": version, "制品摘要": f"sha256:{name}"},
        ).json()["编号"]
        c.post(f"/api/发版单/{rid}/流水线", json={"流水线": "绿"})
        c.post(f"/api/发版单/{rid}/入闸")
        return rid

    def promote(rid: int, env: str) -> None:
        r = c.post(f"/api/发版单/{rid}/晋升", json={"目标环境": env})
        assert r.status_code == 200, r.text

    # 1) 晋升后对账：完整 测->预->产，平账
    healthy = make_release("夹具-平账支付", "4.0.0")
    promote(healthy, "预")
    promote(healthy, "产")

    # 2) 事件缺失：已到产但删掉 预->产 事件
    missing = make_release("夹具-缺事件库存", "2.1.0")
    promote(missing, "预")
    promote(missing, "产")

    # 3) 事件越位：事件写到产，单态拧回 晋升中/预
    stray = make_release("夹具-越位风控", "3.2.1")
    promote(stray, "预")

    # 4) 半截单态：状态已放行、环境还在预
    half = make_release("夹具-半截营销", "5.0.1")
    promote(half, "预")

    # 5) 名册拧花
    roster = make_release("夹具-名册消息", "6.3.0")
    promote(roster, "预")

    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("DELETE FROM promote_events WHERE release_id=? AND seq=2", (missing,))
    yu = conn.execute("SELECT id FROM environments WHERE code='预'").fetchone()["id"]
    chan = conn.execute("SELECT id FROM environments WHERE code='产'").fetchone()["id"]
    conn.execute(
        """INSERT INTO promote_events(release_id, seq, from_env_id, to_env_id, decision, created_at, note)
           VALUES (?, 9, ?, ?, '放行', datetime('now','localtime'), '夹具野事件')""",
        (stray, yu, chan),
    )
    conn.execute(
        "UPDATE releases SET status='晋升中', current_env_id=? WHERE id=?", (yu, stray)
    )
    conn.execute("UPDATE releases SET status='已放行' WHERE id=?", (half,))
    conn.execute(
        "UPDATE app_env_versions SET version='0.0.0-拧花' WHERE app_id=(SELECT app_id FROM releases WHERE id=?) AND env_id=?",
        (roster, yu),
    )
    conn.commit()
    conn.close()

    rep = c.get("/api/对账").json()
    print(f"夹具库已生成：{path}")
    print(f"发版单：平账#{healthy} 缺事件#{missing} 越位#{stray} 半截#{half} 名册#{roster}")
    print(f"对账差额={rep['差额']} 一致={rep['一致']}")
    for d in rep["对账明细"]:
        if d["差额"]:
            print(f"  #{d['编号']} {d['发版单号']} 差额{d['差额']} "
                  f"{[i['类型'] for i in d['差异']]}")
    print("调用 POST /api/对账/纠偏 可一键收敛到发版单状态机真源。")


if __name__ == "__main__":
    build()
