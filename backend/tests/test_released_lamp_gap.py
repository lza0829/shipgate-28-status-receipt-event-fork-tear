"""假已放行收口：四路分测 + 读面加厚。

已放行灯须能由 单态∪事件∪对账∪审计 重放同指；证据撕裂时
详情页、事件列表、对账、名册、总览分布格、审计 全部钉缺口，
纠偏收敛（纠回）后灯才成立。真源选型不变（发版单状态机），
本文件只钉证据撕裂，不重做权威选型。

四路夹具分测：
1. 灯亮事件停预发（半截单态：单态已放行、事件仍停预发）
2. 事件落单态回滚（事件已写到产、单态回滚晋升中/预）
3. 对账拧花（事件链断环，重放必须揭穿假已放行灯）
4. 手改单态与晋升交错半截（手改即收敛，晋升状态闸拦截）
"""
from __future__ import annotations

from conftest import promote_to, seed_release_id


def _detail(client, rid):
    return client.get(f"/api/发版单/{rid}").json()


def _row(report, rid):
    return next(d for d in report["对账明细"] if d["编号"] == rid)


def _env_cell(overview, code):
    return next(x for x in overview["环境分布"] if x["环境"] == code)


def _roster_row(report, app, env):
    return next(r for r in report["名册与实例"] if r["应用"] == app and r["环境"] == env)


def _cross_row(cross, rid):
    return next(r for r in cross["对照"] if r["编号"] == rid)


# ------------------------------------------------------------ 一路：灯亮事件停预发

def test_lamp_on_events_stuck_at_staging_pins_gap_everywhere(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")

    # 半截单态：单态已放行，事件链仍停预发（灯亮事件停）
    conn = raw()
    conn.execute("UPDATE releases SET status='已放行' WHERE id=?", (rid,))
    conn.commit()

    # 详情页：灯面亮但证据未同指，缺口钉死，环境链/名册旁读同屏可开
    d = _detail(client, rid)
    assert d["状态"] == "已放行"
    assert d["当前环境"] == "预"
    assert d["重放环境"] == "预"
    assert d["已放行灯"]["亮"] is True
    assert d["已放行灯"]["成立"] is False
    assert d["假已放行"] is True
    assert d["放行成立"] is False
    assert d["缺口未清"] is True
    assert "状态环境不一致" in d["缺口类型"]
    assert d["环境链"] == ["测", "预"]
    assert isinstance(d["名册旁读"], list) and d["名册旁读"]
    assert "测" in d["各环境名册"] and "预" in d["各环境名册"]
    assert isinstance(d["挂接实例"], list)
    assert isinstance(d["审计"], list)
    ev = d["已放行灯"]["证据"]
    assert ev["单态环境"] == "预" and ev["事件重放环境"] == "预"

    # 对账：重放揭穿假已放行灯
    rep = client.get("/api/对账").json()
    row = _row(rep, rid)
    assert row["假已放行"] is True
    assert row["已放行灯"]["亮"] is True and row["已放行灯"]["成立"] is False
    assert rep["假已放行数"] >= 1
    assert rep["缺口未清"] is True
    assert any(g["编号"] == rid for g in rep["缺口"])

    # 总览：分布格钉缺口，假已放行不得计入成立
    ov = client.get("/api/总览").json()
    assert ov["分布"]["已放行"] >= 1
    assert ov["分布"]["放行缺口"] >= 1
    cell = _env_cell(ov, "预")
    assert cell["缺口数"] >= 1 and cell["假已放行数"] >= 1
    assert ov["缺口未清"] is True
    active_row = next(r for r in ov["在途"] if r["编号"] == rid)
    assert active_row["假已放行"] is True

    # 名册：缺口未清不得当已对齐
    detail = _detail(client, rid)
    roster = _roster_row(rep, detail["应用"], "预")
    assert roster["对齐"] is False
    assert roster["真源缺口未清"] is True

    # 事件列表对照：链上钉缺口
    cross = client.get("/api/晋升事件/对照").json()
    crow = _cross_row(cross, rid)
    assert crow["已放行灯"] is True and crow["放行成立"] is False
    assert crow["缺口未清"] is True
    assert crow["环境链"] == ["测", "预"]

    # 纠偏（纠回）：收敛后灯才成立，四证同指
    out = client.post(f"/api/发版单/{rid}/纠偏").json()
    assert out["对账"]["差额"] == 0
    d = _detail(client, rid)
    assert d["状态"] == "已放行" and d["当前环境"] == "产"
    assert d["环境链"] == ["测", "预", "产"]
    assert d["已放行灯"]["成立"] is True
    assert d["假已放行"] is False
    assert d["缺口未清"] is False
    assert d["审计放行证据"] is True  # 纠偏补录留了审计腿
    assert client.get("/api/对账").json()["一致"] is True
    ov = client.get("/api/总览").json()
    assert ov["真源一致"] is True
    assert ov["分布"]["放行缺口"] == 0
    roster = _roster_row(client.get("/api/对账").json(), d["应用"], "产")
    assert roster["对齐"] is True
    # 审计过滤能查到纠偏痕迹
    au = client.get("/api/审计", params={"类别": "对账", "关联编号": rid}).json()
    assert au and any("纠偏" in x["动作"] for x in au)


# ------------------------------------------------------------ 二路：事件落单态回滚

def test_event_landed_but_state_rolled_back_pins_gap(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")

    # 事件已写到产，单态却回滚/停在 晋升中/预
    conn = raw()
    env_yu = conn.execute("SELECT id FROM environments WHERE code='预'").fetchone()["id"]
    env_chan = conn.execute("SELECT id FROM environments WHERE code='产'").fetchone()["id"]
    conn.execute(
        """INSERT INTO promote_events(release_id, seq, from_env_id, to_env_id, decision, created_at, note)
           VALUES (?, 9, ?, ?, '放行', '2026-11-26 05:00:00', '野事件')""",
        (rid, env_yu, env_chan),
    )
    conn.commit()

    d = _detail(client, rid)
    assert d["状态"] == "晋升中"
    assert d["已放行灯"]["亮"] is False
    assert d["缺口未清"] is True
    assert "事件越位" in d["缺口类型"]
    assert d["重放环境"] == "产"      # 事件已落产
    assert d["当前环境"] == "预"      # 单态停在预

    cross = client.get("/api/晋升事件/对照").json()
    crow = _cross_row(cross, rid)
    assert crow["重放环境"] == "产" and crow["真源环境"] == "预"
    assert crow["缺口未清"] is True

    rep = client.get("/api/对账").json()
    assert any(i["类型"] == "事件越位" for i in _row(rep, rid)["差异"])

    # 纠偏：越位事件作废留痕，单态不回滚事件链
    client.post(f"/api/发版单/{rid}/纠偏")
    d = _detail(client, rid)
    assert d["状态"] == "晋升中" and d["当前环境"] == "预"
    assert [e["目标环境"] for e in d["事件"]] == ["预"]
    assert d["缺口未清"] is False
    all_events = client.get(f"/api/发版单/{rid}/事件", params={"含作废": "true"}).json()
    assert any(e["作废"] == 1 for e in all_events)
    assert client.get("/api/对账").json()["一致"] is True


# ------------------------------------------------------------ 三路：对账拧花（重放揭穿假灯）

def test_reconcile_replay_exposes_fake_lamp_on_broken_chain(client, raw):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    promote_to(client, rid, "产")

    # 对账拧花：事件链断环（抽掉 测→预），单态仍已放行/产
    conn = raw()
    conn.execute("DELETE FROM promote_events WHERE release_id=? AND seq=1", (rid,))
    conn.commit()

    rep = client.get("/api/对账").json()
    row = _row(rep, rid)
    assert row["差额"] >= 1
    assert row["假已放行"] is True          # 灯亮但重放不同指
    assert row["已放行灯"]["成立"] is False
    assert any(i["类型"] in ("事件缺失", "序号断号") for i in row["差异"])

    d = _detail(client, rid)
    assert d["已放行灯"]["亮"] is True and d["已放行灯"]["成立"] is False
    assert d["序号连续"] is False

    # 总览分布格：产格钉缺口，不许当已对齐
    ov = client.get("/api/总览").json()
    assert _env_cell(ov, "产")["缺口数"] >= 1
    assert ov["分布"]["放行缺口"] >= 1

    # 纠偏重建事件链后灯成立
    client.post("/api/对账/纠偏", json={"发版单编号": rid})
    d = _detail(client, rid)
    assert d["状态"] == "已放行" and d["当前环境"] == "产"
    assert [e["目标环境"] for e in d["事件"]] == ["预", "产"]
    assert [e["序号"] for e in d["事件"]] == [1, 2]
    assert d["已放行灯"]["成立"] is True
    assert client.get("/api/对账").json()["一致"] is True


# ------------------------------------------------------------ 四路：手改单态 × 晋升交错半截

def test_manual_edit_and_promote_interleave_converges(client):
    rid = seed_release_id(client)
    promote_to(client, rid, "预")

    # 手改已放行：提交即按真源自收敛，不留半截（灯亮则证据同指）
    resp = client.post(f"/api/发版单/{rid}/状态", json={"状态": "已放行", "备注": "值班手改"})
    assert resp.status_code == 200
    d = resp.json()
    assert d["状态"] == "已放行" and d["当前环境"] == "产"
    assert d["环境链"] == ["测", "预", "产"]
    assert d["已放行灯"]["成立"] is True
    assert d["缺口未清"] is False
    assert d["审计放行证据"] is True

    # 交错晋升：状态闸拦截，已放行单不可再晋升
    r = promote_to(client, rid, "产")
    assert r.status_code == 400

    # 手改回晋升中：事件链同步收束（越位事件作废），长期只一本账
    resp = client.post(f"/api/发版单/{rid}/状态", json={"状态": "晋升中", "备注": "回退半截"})
    assert resp.status_code == 200
    d = resp.json()
    assert d["状态"] == "晋升中" and d["当前环境"] == "预"
    assert [e["目标环境"] for e in d["事件"]] == ["预"]
    assert d["缺口未清"] is False
    assert client.get("/api/对账").json()["一致"] is True
    ov = client.get("/api/总览").json()
    assert ov["真源一致"] is True
    assert ov["分布"]["放行缺口"] == 0


def test_manual_half_state_fixture_pins_gap(client, raw):
    """手改半截夹具（绕开自收敛直改库）：灯亮事件停，各面钉缺口后纠回。"""
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    conn = raw()
    conn.execute(
        "UPDATE releases SET status='已放行', released_at=datetime('now','localtime') WHERE id=?",
        (rid,),
    )
    conn.commit()

    d = _detail(client, rid)
    assert d["已放行灯"]["亮"] is True and d["已放行灯"]["成立"] is False
    assert d["缺口未清"] is True

    # 手改入口再改一次（带正确状态版本）：同事务自收敛，缺口当场清
    rev = d["state_rev"]
    resp = client.post(
        f"/api/发版单/{rid}/状态", json={"状态": "已放行", "状态版本": rev, "备注": "确认放行"}
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["状态"] == "已放行" and d["当前环境"] == "产"
    assert d["已放行灯"]["成立"] is True
    assert d["缺口未清"] is False
    assert client.get("/api/对账").json()["一致"] is True


# ------------------------------------------------------------ 加厚：四证同屏 / 分布格 / 名册 / 审计

def test_detail_same_screen_evidence_when_lamp_valid(client):
    """健康放行：详情一页同屏开出 单态∪事件链∪名册∪审计 四证。"""
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    promote_to(client, rid, "产")

    d = _detail(client, rid)
    assert d["已放行灯"]["亮"] is True and d["已放行灯"]["成立"] is True
    assert d["假已放行"] is False
    assert d["环境链"] == ["测", "预", "产"]
    assert d["重放环境"] == "产" and d["当前环境"] == "产"
    # 名册旁读（跨环）：各环境版本齐开
    assert set(d["各环境名册"].keys()) == {"测", "预", "产"}
    assert d["各环境名册"]["产"] == d["目标版本"]
    assert d["名册版本"] == d["目标版本"]
    # 挂接行：产环境实例挂在该单下
    hooked = [(x["环境"], x["版本"]) for x in d["挂接实例"]]
    assert ("产", d["目标版本"]) in hooked
    # 审计腿：晋升到产有痕
    assert any(x["动作"] == "晋升到产" for x in d["审计"])
    assert d["审计放行证据"] is True
    ev = d["已放行灯"]["证据"]
    assert ev["单态环境"] == "产" and ev["事件重放环境"] == "产"
    assert ev["名册版本"] == d["目标版本"]


def test_overview_inflight_cells_and_gap_list(client, raw):
    """在途分布格：缺口数钉在 env 格上；缺口清单可跳到单单。"""
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    conn = raw()
    conn.execute("UPDATE releases SET status='已放行' WHERE id=?", (rid,))
    conn.commit()

    ov = client.get("/api/总览").json()
    cell = _env_cell(ov, "预")
    assert cell["在途数"] >= 1
    assert cell["缺口数"] >= 1
    assert cell["假已放行数"] >= 1
    gap = next(g for g in ov["缺口"] if g["编号"] == rid)
    assert gap["假已放行"] is True
    assert "状态环境不一致" in gap["缺口类型"]
    assert ov["缺口数"] >= 1

    # 纠偏后分布格回落
    client.post(f"/api/发版单/{rid}/纠偏")
    ov = client.get("/api/总览").json()
    assert _env_cell(ov, "预")["缺口数"] == 0
    assert _env_cell(ov, "产")["假已放行数"] == 0
    assert ov["缺口未清"] is False


def test_events_cross_read_marks_torn_and_healthy(client, raw):
    """事件列表对照：健康单链=真源，撕裂单钉缺口类型。"""
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    promote_to(client, rid, "产")

    cross = client.get("/api/晋升事件/对照").json()
    crow = _cross_row(cross, rid)
    assert crow["环境链"] == ["测", "预", "产"]
    assert crow["真源环境"] == "产" and crow["重放环境"] == "产"
    assert crow["已放行灯"] is True and crow["放行成立"] is True
    assert crow["缺口未清"] is False
    assert crow["名册版本"] == crow["目标版本"]

    conn = raw()
    conn.execute("DELETE FROM promote_events WHERE release_id=? AND seq=2", (rid,))
    conn.commit()
    cross = client.get("/api/晋升事件/对照").json()
    crow = _cross_row(cross, rid)
    assert crow["重放环境"] == "预" and crow["真源环境"] == "产"
    assert crow["放行成立"] is False and crow["假已放行"] is True
    assert "事件缺失" in crow["缺口类型"]
    assert cross["缺口未清"] is True


def test_roster_double_book_flagged_and_repaired(client, raw):
    """名册双账：真源环境格的名册版本被拧花时钉双账，纠偏对齐。"""
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    detail = _detail(client, rid)
    app = detail["应用"]

    conn = raw()
    conn.execute(
        """UPDATE app_env_versions SET version='0.0.0-拧花'
           WHERE app_id=(SELECT app_id FROM releases WHERE id=?)
             AND env_id=(SELECT current_env_id FROM releases WHERE id=?)""",
        (rid, rid),
    )
    conn.commit()

    rep = client.get("/api/对账").json()
    roster = _roster_row(rep, app, "预")
    assert roster["双账"] is True
    assert roster["对齐"] is False
    assert roster["真源目标版本"] == detail["目标版本"]
    assert any(i["类型"] == "名册版本不一致" for i in _row(rep, rid)["差异"])

    client.post(f"/api/发版单/{rid}/纠偏")
    rep = client.get("/api/对账").json()
    roster = _roster_row(rep, app, "预")
    assert roster["双账"] is False
    assert roster["对齐"] is True
    assert roster["名册版本"] == detail["目标版本"]


def test_audit_filter_reaches_repair_and_manual_trail(client, raw):
    """审计过滤：手改与纠偏痕迹可按 类别/关联编号/动作/关键词 摸到。"""
    rid = seed_release_id(client)
    promote_to(client, rid, "预")
    conn = raw()
    conn.execute("UPDATE releases SET status='已放行' WHERE id=?", (rid,))
    conn.commit()

    client.post(f"/api/发版单/{rid}/状态", json={"状态": "已放行", "备注": "确认放行"})

    by_kind = client.get("/api/审计", params={"类别": "发版单", "关联编号": rid}).json()
    assert any(x["动作"] == "手改状态" for x in by_kind)
    by_action = client.get("/api/审计", params={"动作": "纠偏", "关联编号": rid}).json()
    assert by_action  # 手改后自收敛纠偏留痕
    by_keyword = client.get("/api/审计", params={"关键词": "确认放行"}).json()
    assert by_keyword and all(x["关联编号"] == rid for x in by_keyword)
    # 审计腿能重放已放行灯
    d = _detail(client, rid)
    assert d["审计放行证据"] is True
    assert any(x["动作"] == "手改状态" for x in d["审计"])
