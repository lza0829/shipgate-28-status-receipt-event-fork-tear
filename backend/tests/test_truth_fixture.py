"""同一夹具：发版单状态机、推进戳、事件序号、缺事件纠偏、名册版本、
总览分布格、对账差额、审计查询条件一起对读。

真源选型（实现者自决）：发版单状态机为准。
"""
from __future__ import annotations

import concurrent.futures
import threading

from conftest import promote_to, seed_release_id


def _detail(client, rid):
    return client.get(f"/api/发版单/{rid}").json()


def _row(report, rid):
    return next(d for d in report["对账明细"] if d["编号"] == rid)


# ------------------------------------------------------------ 晋升后对账（黄金夹具）

def test_post_promotion_reconcile_is_balanced(client):
    rid = seed_release_id(client)

    r = promote_to(client, rid, "预")
    assert r.status_code == 200
    body = r.json()
    assert body["状态"] == "晋升中"
    assert body["当前环境"] == "预"
    assert body["state_rev"] >= 1
    assert body["状态机推进戳"]

    r2 = promote_to(client, rid, "产")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["状态"] == "已放行"
    assert body2["当前环境"] == "产"
    seqs = [e["序号"] for e in body2["事件"]]
    assert seqs == [1, 2]

    # 对账：差额 0、一致
    rep = client.get("/api/对账").json()
    assert rep["差额"] == 0
    assert rep["一致"] is True
    assert rep["平账"] is True
    assert rep["对账结果"] == "平"
    row = _row(rep, rid)
    assert row["真源状态"] == "已放行"
    assert row["真源环境"] == "产"
    assert row["重放环境"] == "产"
    assert row["环境链"] == ["测", "预", "产"]
    assert row["差额"] == 0

    # 名册版本列与真源目标版本对齐
    roster = {(x["应用"], x["环境"]): x["名册版本"] for x in rep["名册与实例"]}
    detail = _detail(client, rid)
    assert roster[(detail["应用"], "产")] == detail["目标版本"]

    # 总览分布格：已放行 +1，环境分布产格为 1
    ov = client.get("/api/总览").json()
    assert ov["分布"]["已放行"] == 1
    env_cell = next(x for x in ov["环境分布"] if x["环境"] == "产")
    assert env_cell["单据数"] == 1
    assert ov["对账差额"] == 0
    assert ov["真源一致"] is True

    # 审计查询条件：类别 + 关联编号
    au = client.get("/api/审计", params={"类别": "晋升", "关联编号": rid}).json()
    assert len(au) == 2
    assert all(x["关联编号"] == rid for x in au)

    # 事件列表端点
    ev = client.get("/api/晋升事件", params={"发版单编号": rid}).json()
    assert [(e["序号"], e["目标环境"]) for e in ev] == [(1, "预"), (2, "产")]
    ev2 = client.get(f"/api/发版单/{rid}/事件").json()
    assert len(ev2) == 2


def test_state_stamp_advances_monotonically(client):
    rid = seed_release_id(client)
    d0 = _detail(client, rid)
    s0 = d0["状态机推进戳"]
    rev0 = d0["state_rev"]
    promote_to(client, rid, "预")
    s1 = _detail(client, rid)["状态机推进戳"]
    promote_to(client, rid, "产")
    d2 = _detail(client, rid)
    s2 = d2["状态机推进戳"]
    assert s0 and s1 and s2
    assert s0 <= s1 <= s2
    assert d2["state_rev"] == rev0 + 2


# ------------------------------------------------------------ 事件缺失 + 纠偏夹具

def test_missing_event_detected_and_backfilled(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    promote_to(client, rid, "产")

    conn = raw()
    conn.execute("DELETE FROM promote_events WHERE release_id=? AND seq=2", (rid,))
    conn.commit()

    # 对账必须看出缺事件，而不是只改汇总
    rep = client.get("/api/对账").json()
    row = _row(rep, rid)
    assert row["差额"] >= 1
    kinds = [i["类型"] for i in row["差异"]]
    assert "事件缺失" in kinds
    assert row["重放环境"] == "预"
    assert row["真源环境"] == "产"
    assert rep["差额"] >= 1
    assert rep["一致"] is False

    # 详情页同样能读到不一致
    d = _detail(client, rid)
    assert d["一致"] is False
    assert any(i["类型"] == "事件缺失" for i in d["差异"])

    # 缺事件纠偏入口（单据级）
    resp = client.post(f"/api/发版单/{rid}/纠偏")
    assert resp.status_code == 200
    out = resp.json()
    assert any("补录" in a for a in out["修复"]["修复项"])
    assert out["对账"]["差额"] == 0

    # 纠偏后：单态仍是已放行/产（状态机真源不被重放盖掉），事件链补齐
    d = _detail(client, rid)
    assert d["状态"] == "已放行"
    assert d["当前环境"] == "产"
    assert [e["序号"] for e in d["事件"]] == [1, 2]
    assert d["事件"][1]["来源"] == "补录"
    assert d["一致"] is True

    # 全局对账平、总览一致
    assert client.get("/api/对账").json()["差额"] == 0
    assert client.get("/api/总览").json()["真源一致"] is True

    # 纠偏写审计，可按类别查到
    au = client.get("/api/审计", params={"类别": "对账", "关联编号": rid}).json()
    assert au and any(x["动作"] == "纠偏" for x in au)

    # 幂等：再次纠偏无修复项且仍平
    again = client.post("/api/对账/纠偏", json={"发版单编号": rid}).json()
    assert again["修复"]["修复项"] == []
    assert again["差额"] == 0


def test_missing_middle_event_rebuilds_chain(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    promote_to(client, rid, "产")
    conn = raw()
    conn.execute("DELETE FROM promote_events WHERE release_id=? AND seq=1", (rid,))
    conn.commit()

    row = _row(client.get("/api/对账").json(), rid)
    assert row["差额"] >= 1
    assert any(i["类型"] == "事件缺失" for i in row["差异"])

    out = client.post("/api/对账/纠偏", json={"发版单编号": rid}).json()
    assert out["差额"] == 0
    d = _detail(client, rid)
    assert d["当前环境"] == "产"
    assert [e["目标环境"] for e in d["事件"]] == ["预", "产"]
    assert [e["序号"] for e in d["事件"]] == [1, 2]


# ------------------------------------------------------------ 半截单态与事件拧花

def test_event_ahead_of_state_is_voided_to_truth(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")

    # 模拟“事件已写到产、单态仍晋升中/预”的半截拧花
    conn = raw()
    env_yu = conn.execute("SELECT id FROM environments WHERE code='预'").fetchone()["id"]
    env_chan = conn.execute("SELECT id FROM environments WHERE code='产'").fetchone()["id"]
    conn.execute(
        """INSERT INTO promote_events(release_id, seq, from_env_id, to_env_id, decision, created_at)
           VALUES (?, 9, ?, ?, '放行', ?)""",
        (rid, env_yu, env_chan, "2026-11-26 05:00:00"),
    )
    conn.commit()

    row = _row(client.get("/api/对账").json(), rid)
    assert any(i["类型"] == "事件越位" for i in row["差异"])
    assert row["重放环境"] == "产"

    out = client.post(f"/api/发版单/{rid}/纠偏").json()
    assert out["差额"] == 0

    d = _detail(client, rid)
    assert d["状态"] == "晋升中"
    assert d["当前环境"] == "预"
    assert [e["目标环境"] for e in d["事件"]] == ["预"]
    # 作废事件仍可在“全部事件”里留痕
    all_events = client.get(
        f"/api/发版单/{rid}/事件", params={"含作废": "true"}
    ).json()
    assert any(e["作废"] == 1 for e in all_events)


def test_status_ahead_half_state_converges_env_and_events(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")

    # 单态已放行，但当前环境还挂预、事件只到预
    conn = raw()
    conn.execute("UPDATE releases SET status='已放行' WHERE id=?", (rid,))
    conn.commit()

    row = _row(client.get("/api/对账").json(), rid)
    assert any(i["类型"] == "状态环境不一致" for i in row["差异"])

    out = client.post("/api/对账/纠偏").json()
    assert out["差额"] == 0

    d = _detail(client, rid)
    # 状态机为锚：已放行 -> 当前环境产，并补齐事件
    assert d["状态"] == "已放行"
    assert d["当前环境"] == "产"
    assert [e["目标环境"] for e in d["事件"]] == ["预", "产"]
    assert client.get("/api/对账").json()["差额"] == 0


def test_roster_drift_is_repaired_from_release_truth(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    conn = raw()
    conn.execute(
        """UPDATE app_env_versions SET version='0.0.1'
           WHERE app_id=(SELECT app_id FROM releases WHERE id=?)
             AND env_id=(SELECT current_env_id FROM releases WHERE id=?)""",
        (rid, rid),
    )
    conn.commit()

    row = _row(client.get("/api/对账").json(), rid)
    assert any(i["类型"] == "名册版本不一致" for i in row["差异"])

    client.post(f"/api/发版单/{rid}/纠偏")
    rep = client.get("/api/对账").json()
    assert _row(rep, rid)["差额"] == 0


# ------------------------------------------------------------ 并发晋升夹具

def test_concurrent_identical_promotion_writes_one_event(client):
    rid = seed_release_id(client)
    barrier = threading.Barrier(8)

    def hit(_):
        barrier.wait()
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as cc:
            resp = cc.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})
            return resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(hit, range(8)))

    assert codes.count(200) == 1
    assert all(code in (400, 409) for code in codes if code != 200)

    d = _detail(client, rid)
    assert d["状态"] == "晋升中"
    assert d["当前环境"] == "预"
    assert len(d["事件"]) == 1
    assert d["事件"][0]["序号"] == 1
    assert client.get("/api/对账").json()["差额"] == 0


# ------------------------------------------------------------ 手改状态 vs 晋升：只许一套真源

def test_manual_status_change_converges_immediately(client):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")

    resp = client.post(f"/api/发版单/{rid}/状态", json={"状态": "已放行", "备注": "值班手改"})
    assert resp.status_code == 200
    d = resp.json()
    assert d["状态"] == "已放行"
    assert d["当前环境"] == "产"
    assert d["差额"] == 0
    assert [e["目标环境"] for e in d["事件"]] == ["预", "产"]
    assert client.get("/api/对账").json()["差额"] == 0

    # 审计里同时留手改与纠偏痕迹
    au = client.get("/api/审计", params={"关联编号": rid}).json()
    actions = " ".join(x["动作"] for x in au)
    assert "手改状态" in actions


def test_optimistic_revision_conflict(client):
    rid = seed_release_id(client)
    d = _detail(client, rid)
    stale = d["state_rev"]
    promote_to(client, rid, "预")
    resp = client.post(
        f"/api/发版单/{rid}/状态", json={"状态": "已关闭", "状态版本": stale}
    )
    assert resp.status_code == 409


# ------------------------------------------------------------ 同笔事务：状态与事件同生共死

def test_state_advancement_and_event_commit_atomically(client, raw, monkeypatch):
    import pytest

    import app.routers.promote as promote_router

    rid = seed_release_id(client)
    rev0 = _detail(client, rid)["state_rev"]

    def _boom(*_a, **_kw):
        raise RuntimeError("投影写入强制失败")

    # 状态推进 + 事件插入之后的名册投影炸掉：整个工作单元必须回滚
    monkeypatch.setattr(promote_router, "set_app_env_version", _boom)

    with pytest.raises(RuntimeError):
        client.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "预"})

    conn = raw()
    row = conn.execute("SELECT status, current_env_id, state_rev FROM releases WHERE id=?", (rid,)).fetchone()
    assert row["status"] == "已入闸"
    assert row["state_rev"] == rev0
    ev_count = conn.execute(
        "SELECT COUNT(*) AS c FROM promote_events WHERE release_id=?", (rid,)
    ).fetchone()["c"]
    assert ev_count == 0
    # 回滚后应用仍可正常晋升，证明连接/事务没有被污染
    monkeypatch.undo()
    assert promote_to(client, rid, "预").status_code == 200
    assert _detail(client, rid)["事件"][0]["序号"] == 1


# ------------------------------------------------------------ 手改状态 × 晋升 并发：长期只许一本账

def test_concurrent_manual_and_promote_end_single_truth(client):
    rid = seed_release_id(client)
    assert promote_to(client, rid, "预").status_code == 200
    barrier = threading.Barrier(8)

    def hit(i):
        barrier.wait()
        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as cc:
            if i % 2 == 0:
                resp = cc.post(f"/api/发版单/{rid}/晋升", json={"目标环境": "产"})
                return "promote", resp.status_code
            resp = cc.post(f"/api/发版单/{rid}/状态", json={"状态": "已放行"})
            return "manual", resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(hit, range(8)))

    promote_codes = [code for kind, code in results if kind == "promote"]
    manual_codes = [code for kind, code in results if kind == "manual"]
    # 不带版本号的手改始终成功；并发晋升至多一个成功，其余被状态闸拦下
    assert all(code == 200 for code in manual_codes)
    assert promote_codes.count(200) <= 1
    assert all(code in (200, 400, 409) for code in promote_codes)

    # 无论调度顺序如何，终态唯一：已放行 / 产 / 稠密两序号 / 对账平
    d = _detail(client, rid)
    assert d["状态"] == "已放行"
    assert d["当前环境"] == "产"
    assert [e["目标环境"] for e in d["事件"]] == ["预", "产"]
    assert [e["序号"] for e in d["事件"]] == [1, 2]
    assert d["一致"] is True
    assert client.get("/api/对账").json()["差额"] == 0
    # 总览同样只认这一本真源
    assert client.get("/api/总览").json()["真源一致"] is True


# ------------------------------------------------------------ 审计查询条件

def test_audit_filters(client):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")

    assert len(client.get("/api/审计", params={"类别": "晋升"}).json()) >= 1
    assert len(client.get("/api/审计", params={"kind": "晋升", "ref_id": rid}).json()) == 1
    assert client.get("/api/审计", params={"动作": "不存在的动作xyz"}).json() == []
    got = client.get("/api/审计", params={"关键词": "晋升到预"}).json()
    assert got and all("晋升到预" in (x["动作"] + x["备注"]) for x in got)
    # 时间条件不报错且能框住
    got2 = client.get(
        "/api/审计", params={"开始时间": "2000-01-01", "结束时间": "2100-01-01"}
    ).json()
    assert len(got2) >= 1
    assert client.get("/api/审计", params={"开始时间": "2100-01-01"}).json() == []
