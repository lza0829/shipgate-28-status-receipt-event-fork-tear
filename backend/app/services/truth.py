"""晋升结果唯一真源：发版单状态机（releases.status + current_env_id + state_rev）。

约定：
- 状态推进与 promote_events 写入在同一个 db() 工作单元内提交，同笔成败。
- 事件流是附件/证据：对账时按每单 seq 重放环境链，仅用于与真源比对、发现差异，
  绝不用重放结果反向盖写发版单状态。
- 名册 app_env_versions 是下游投影，只允许由状态推进/纠偏按发版单真源对齐，
  不允许被事件重放偷偷改写。
- 纠偏 POST /对账/纠偏（及 /发版单/{id}/纠偏）把事件链、名册收敛回发版单真源，
  全过程写审计；重复执行幂等。
"""
from __future__ import annotations

from fastapi import HTTPException

from app.db import row_to_dict, rows_to_list
from app.services.common import get_release, now_str, set_app_env_version

# 状态机状态 <-> 当前环境 的正定关系（晋升段）
STATUS_TO_ENV = {"已入闸": "测", "晋升中": "预", "已放行": "产"}
ENV_TO_STATUS = {"测": "已入闸", "预": "晋升中", "产": "已放行"}
PROMOTION_STATUSES = tuple(STATUS_TO_ENV.keys())
# 回滚段写闸另立，不纳入晋升真源的状态-环境正定校验
ROLLBACK_STATUSES = ("回滚中", "已回滚")


# ---------------------------------------------------------------- 环境索引

def env_index(conn):
    envs = rows_to_list(conn.execute("SELECT * FROM environments ORDER BY sort_order").fetchall())
    by_id = {e["id"]: e for e in envs}
    id_by_code = {e["code"]: e["id"] for e in envs}
    idx_by_id = {e["id"]: i for i, e in enumerate(envs)}
    idx_by_code = {e["code"]: i for i, e in enumerate(envs)}
    return envs, by_id, id_by_code, idx_by_id, idx_by_code


# ---------------------------------------------------------------- 事件流水

def raw_events(conn, release_id: int, valid_only: bool = True):
    sql = "SELECT * FROM promote_events WHERE release_id=?"
    if valid_only:
        sql += " AND COALESCE(superseded,0)=0 AND decision='放行'"
    sql += " ORDER BY CASE WHEN seq IS NULL THEN 1 ELSE 0 END, seq, id"
    return conn.execute(sql, (release_id,)).fetchall()


def next_seq(conn, release_id: int) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(seq), 0) + 1 AS n
        FROM promote_events
        WHERE release_id=? AND COALESCE(superseded,0)=0
        """,
        (release_id,),
    ).fetchone()
    return int(row["n"])


def add_event(
    conn,
    release_id: int,
    from_env_id: int | None,
    to_env_id: int,
    note: str = "",
    origin: str = "正常",
    seq: int | None = None,
    created_at: str | None = None,
    decision: str = "放行",
) -> int:
    if seq is None:
        seq = next_seq(conn, release_id)
    cur = conn.execute(
        """
        INSERT INTO promote_events(
          release_id, seq, from_env_id, to_env_id, decision, created_at, note, origin, superseded
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (release_id, seq, from_env_id, to_env_id, decision, created_at or now_str(), note, origin),
    )
    return cur.lastrowid


def event_chain_view(conn, release_id: int, include_voided: bool = False) -> list[dict]:
    sql = """
        SELECT p.id AS 编号, p.release_id AS 发版单编号, p.seq AS 序号, p.seq AS seq,
               p.from_env_id AS 起始环境编号, ef.code AS 起始环境, ef.name AS 起始环境名,
               p.to_env_id AS 目标环境编号, et.code AS 目标环境, et.name AS 目标环境名,
               p.decision AS 裁决, p.created_at AS 时间, p.created_at AS created_at,
               p.note AS 备注, p.origin AS 来源,
               COALESCE(p.superseded,0) AS 作废, COALESCE(p.superseded,0) AS superseded
        FROM promote_events p
        LEFT JOIN environments ef ON ef.id = p.from_env_id
        JOIN environments et ON et.id = p.to_env_id
        WHERE p.release_id=?
    """
    if not include_voided:
        sql += " AND COALESCE(p.superseded,0)=0"
    sql += " ORDER BY CASE WHEN p.seq IS NULL THEN 1 ELSE 0 END, p.seq, p.id"
    return rows_to_list(conn.execute(sql, (release_id,)).fetchall())


# ---------------------------------------------------------------- 重放核验

def _issue(kind: str, code: str, desc: str, **extra) -> dict:
    d = {"类型": kind, "code": code, "说明": desc}
    d.update(extra)
    return d


def analyze_release(conn, r, indexes=None) -> dict:
    """对一张发版单做真源/事件重放/名册三方核验，返回结构化差异。"""
    if indexes is None:
        indexes = env_index(conn)
    envs, by_id, id_by_code, idx_by_id, idx_by_code = indexes

    rid = r["id"]
    status = r["status"]
    truth_env_id = r["current_env_id"]
    truth_code = by_id.get(truth_env_id, {}).get("code") if truth_env_id else None

    admitted = bool(r["admitted_at"]) or status != "待入闸"
    baseline_id = id_by_code.get("测") if admitted else None

    events = raw_events(conn, rid, valid_only=True)
    seq_values = [e["seq"] for e in events if e["seq"] is not None]
    dense_seq_ok = len(seq_values) == len(events) and seq_values == list(range(1, len(seq_values) + 1))

    # 重放环境链
    expected_from = baseline_id
    continuity_ok = True
    for e in events:
        if expected_from is not None and e["from_env_id"] is not None:
            if e["from_env_id"] != expected_from:
                continuity_ok = False
        expected_from = e["to_env_id"]
    replay_env_id = events[-1]["to_env_id"] if events else baseline_id
    replay_code = by_id.get(replay_env_id, {}).get("code") if replay_env_id else None
    replay_status = ENV_TO_STATUS.get(replay_code) if replay_code else ("待入闸" if not admitted else None)

    issues: list[dict] = []

    # 1) 单态状态机 vs 当前环境字段（半截单态）。状态机 status 为锚，环境列向其看齐。
    expected_status = None
    expected_env_code = STATUS_TO_ENV.get(status) if status in STATUS_TO_ENV else None
    if status in STATUS_TO_ENV:
        if truth_env_id is None:
            issues.append(_issue(
                "状态环境不一致", "status_env_mismatch",
                f"单态为「{status}」但当前环境为空，按状态机应落在「{expected_env_code}」",
                真源状态=status, 真源环境=None,
                应为环境=expected_env_code, 应为状态=status,
            ))
        else:
            expected_status = ENV_TO_STATUS.get(truth_code)
            canonical_env = STATUS_TO_ENV.get(status)
            if canonical_env and truth_code != canonical_env:
                issues.append(_issue(
                    "状态环境不一致", "status_env_mismatch",
                    f"状态机为「{status}」，当前环境却挂在「{truth_code}」，应为「{canonical_env}」",
                    真源状态=status, 真源环境=truth_code,
                    应为状态=status, 应为环境=canonical_env,
                    环境对应状态=expected_status,
                ))
    elif status == "待入闸" and truth_env_id is not None:
        issues.append(_issue(
            "状态环境不一致", "status_env_mismatch",
            "单据仍为待入闸却挂了当前环境",
            真源状态=status, 真源环境=truth_code, 应为状态="待入闸", 应为环境=None,
        ))

    # 2) 事件流重放 vs 真源当前环境
    missing_hops: list[str] = []
    stray_events: list[dict] = []
    if admitted:
        if truth_env_id is None and replay_env_id is not None:
            stray_events = [dict(e) for e in events]
            issues.append(_issue(
                "事件越位", "stray_event",
                "真源无当前环境，但晋升事件已写到 " + (replay_code or "?") + "，事件与单态双账",
                重放环境=replay_code, 事件数=len(events),
            ))
        elif truth_env_id is not None:
            ti = idx_by_id.get(truth_env_id)
            ri = idx_by_id.get(replay_env_id) if replay_env_id is not None else None
            if ri is None:
                issues.append(_issue(
                    "事件缺失", "missing_event",
                    "已入闸后的晋升事件链不存在", 真源环境=truth_code,
                ))
            elif ti is not None and ti > ri:
                chain_codes = [envs[i]["code"] for i in range(ri, ti + 1)]
                missing_hops = [f"{envs[i]['code']}→{envs[i + 1]['code']}" for i in range(ri, ti)]
                reason = "；事件链存在缺环" if not continuity_ok else ""
                issues.append(_issue(
                    "事件缺失", "missing_event",
                    f"真源当前环境为「{truth_code}」，事件重放只到「{replay_code}」，缺 {('、'.join(missing_hops))}{reason}",
                    真源环境=truth_code, 重放环境=replay_code, 缺失环节=missing_hops,
                    缺失数=len(missing_hops), 序号断号=not dense_seq_ok,
                ))
            elif ri is not None and ri > ti:
                stray = [e for e in events if idx_by_id.get(e["to_env_id"], -1) > ti]
                stray_events = [dict(e) for e in stray]
                issues.append(_issue(
                    "事件越位", "stray_event",
                    f"事件已写到「{replay_code}」，真源当前环境只在「{truth_code}」，单态落后于事件",
                    真源环境=truth_code, 重放环境=replay_code,
                    越位事件编号=[e["id"] for e in stray], 越位事件数=len(stray),
                ))
            elif not continuity_ok:
                issues.append(_issue(
                    "事件缺失", "missing_event",
                    "事件链 from/to 不衔接，存在缺事件（半截流水）",
                    真源环境=truth_code, 重放环境=replay_code, 序号断号=not dense_seq_ok,
                ))
            elif not dense_seq_ok:
                issues.append(_issue(
                    "序号断号", "seq_gap",
                    f"事件序号不连续：{seq_values}", 序号=seq_values,
                ))

    # 3) 名册版本 vs 真源目标版本（下游投影核验）
    roster_version = None
    if truth_env_id is not None and status != "已关闭":
        v = conn.execute(
            "SELECT version FROM app_env_versions WHERE app_id=? AND env_id=?",
            (r["app_id"], truth_env_id),
        ).fetchone()
        roster_version = v["version"] if v else None
        if (roster_version or "") != (r["target_version"] or ""):
            issues.append(_issue(
                "名册版本不一致", "roster_mismatch",
                f"「{truth_code}」名册版本为「{roster_version or '空'}」，真源目标版本为「{r['target_version']}」",
                名册版本=roster_version, 应有版本=r["target_version"], 环境=truth_code,
            ))

    diff = len(issues)
    env_chain = []
    if baseline_id is not None:
        env_chain.append(by_id[baseline_id]["code"])
    for e in events:
        code = by_id.get(e["to_env_id"], {}).get("code")
        if code and (not env_chain or env_chain[-1] != code):
            env_chain.append(code)
    return {
        "编号": rid,
        "发版单号": r["serial"],
        "应用编号": r["app_id"],
        "真源": "发版单状态机",
        "真源状态": status,
        "真源环境编号": truth_env_id,
        "真源环境": truth_code,
        "当前环境": truth_code,
        "基线环境": "测" if baseline_id else None,
        "环境链": env_chain,
        "重放链": env_chain,
        "重放环境编号": replay_env_id,
        "重放环境": replay_code,
        "重放状态": replay_status,
        "是否已放行": status == "已放行" and truth_code == "产",
        "已放行": status == "已放行",
        "事件数": len(events),
        "事件序号": seq_values,
        "序号连续": dense_seq_ok,
        "名册版本": roster_version,
        "差额": diff,
        "差异数": diff,
        "一致": diff == 0,
        "差异": issues,
        "异常": issues,
    }


# ---------------------------------------------------------------- 纠偏

def _void_event(conn, event_id: int) -> None:
    conn.execute("UPDATE promote_events SET superseded=1 WHERE id=?", (event_id,))


def _renumber_events(conn, release_id: int) -> bool:
    rows = raw_events(conn, release_id, valid_only=True)
    seq_values = [r["seq"] for r in rows]
    if seq_values == list(range(1, len(rows) + 1)) and all(s is not None for s in seq_values):
        return False
    conn.execute(
        "UPDATE promote_events SET seq=NULL WHERE release_id=? AND COALESCE(superseded,0)=0",
        (release_id,),
    )
    for i, row in enumerate(rows, start=1):
        conn.execute("UPDATE promote_events SET seq=? WHERE id=?", (i, row["id"]))
    return True


def repair_release(conn, release_id: int) -> dict:
    """按发版单状态机真源收敛单态、事件链与名册。必须运行在 db() 工作单元内。"""
    r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    if not r:
        raise HTTPException(404, "发版单不存在")

    indexes = env_index(conn)
    envs, by_id, id_by_code, idx_by_id, idx_by_code = indexes
    actions: list[str] = []
    now = now_str()

    # ---- 1) 半截单态归位：状态机 status 为锚，当前环境列/时间戳向状态看齐
    status, truth_env_id = r["status"], r["current_env_id"]
    new_status, new_env_id = status, truth_env_id
    if status in STATUS_TO_ENV:
        canonical_code = STATUS_TO_ENV[status]
        canonical_env_id = id_by_code[canonical_code]
        if truth_env_id != canonical_env_id:
            new_env_id = canonical_env_id
            if truth_env_id is None:
                actions.append(f"当前环境按状态机补登为「{canonical_code}」")
            else:
                old_code = by_id.get(truth_env_id, {}).get("code", truth_env_id)
                actions.append(f"当前环境由「{old_code}」归位为状态机所定「{canonical_code}」")
    elif status == "待入闸" and truth_env_id is not None:
        new_env_id = None
        actions.append("清空待入闸单误挂的当前环境")

    if new_status != status or new_env_id != truth_env_id:
        sql = """
            UPDATE releases
               SET status=?, current_env_id=?, state_rev=state_rev+1, state_advanced_at=?
        """
        params: list = [new_status, new_env_id, now]
        if new_status == "已放行":
            sql += ", released_at=COALESCE(released_at, ?)"
            params.append(now)
        sql += " WHERE id=?"
        params.append(release_id)
        conn.execute(sql, params)

    r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    status, truth_env_id = r["status"], r["current_env_id"]
    admitted = bool(r["admitted_at"]) or status != "待入闸"
    baseline_id = id_by_code.get("测") if admitted else None

    # ---- 2) 事件链收敛到真源当前环境
    if not admitted or truth_env_id is None:
        for e in raw_events(conn, release_id):
            _void_event(conn, e["id"])
            actions.append(f"作废无真源对应的越位事件#{e['id']}")
    else:
        truth_idx = idx_by_id[truth_env_id]
        # 2a) 作废超过真源环境的越位事件
        for e in raw_events(conn, release_id):
            to_idx = idx_by_id.get(e["to_env_id"])
            if to_idx is not None and to_idx > truth_idx:
                _void_event(conn, e["id"])
                actions.append(f"作废越位事件#{e['id']}（目标 {by_id[e['to_env_id']]['code']}）")

        events = raw_events(conn, release_id)
        expected_from = baseline_id
        continuity_ok = True
        for e in events:
            if expected_from is not None and e["from_env_id"] is not None and e["from_env_id"] != expected_from:
                continuity_ok = False
            expected_from = e["to_env_id"]
        terminal_id = events[-1]["to_env_id"] if events else baseline_id
        terminal_idx = idx_by_id.get(terminal_id) if terminal_id is not None else None

        if terminal_idx is not None and terminal_idx < truth_idx:
            if continuity_ok:
                # 2b) 追加缺失的逐跳事件（缺事件纠偏入口的主路径）
                start_idx = terminal_idx
                prev_id = terminal_id
                for i in range(start_idx + 1, truth_idx + 1):
                    to_id = envs[i]["id"]
                    add_event(
                        conn, release_id, prev_id, to_id,
                        note="对账纠偏：按发版单真源补录缺失晋升事件",
                        origin="补录", created_at=r["state_advanced_at"] or now,
                    )
                    actions.append(f"补录事件 {envs[i - 1]['code']}→{envs[i]['code']}")
                    prev_id = to_id
            else:
                # 链断裂且无法局部衔接：作废残链，按标准环境链重建附件流水
                for e in events:
                    _void_event(conn, e["id"])
                prev_id = baseline_id
                for i in range(1, truth_idx + 1):
                    to_id = envs[i]["id"]
                    add_event(
                        conn, release_id, prev_id, to_id,
                        note="对账纠偏：事件断链，按发版单真源重建",
                        origin="补录", created_at=r["state_advanced_at"] or now,
                    )
                    actions.append(f"重建事件 {envs[i - 1]['code']}→{envs[i]['code']}")
                    prev_id = to_id
        elif terminal_idx == truth_idx and not continuity_ok:
            for e in events:
                _void_event(conn, e["id"])
            prev_id = baseline_id
            for i in range(1, truth_idx + 1):
                to_id = envs[i]["id"]
                add_event(
                    conn, release_id, prev_id, to_id,
                    note="对账纠偏：事件断链，按发版单真源重建",
                    origin="补录", created_at=r["state_advanced_at"] or now,
                )
                actions.append(f"重建事件 {envs[i - 1]['code']}→{envs[i]['code']}")
                prev_id = to_id
        else:
            if _renumber_events(conn, release_id):
                actions.append("重整事件序号为稠密连续序号")

    # ---- 3) 名册按发版单真源对齐（非事件重放偷改，留审计）
    r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    if r["current_env_id"] and r["status"] != "已关闭":
        v = conn.execute(
            "SELECT version FROM app_env_versions WHERE app_id=? AND env_id=?",
            (r["app_id"], r["current_env_id"]),
        ).fetchone()
        roster_version = v["version"] if v else None
        if (roster_version or "") != (r["target_version"] or ""):
            set_app_env_version(conn, r["app_id"], r["current_env_id"], r["target_version"])
            actions.append(
                f"名册版本由「{roster_version or '空'}」对齐为「{r['target_version']}」"
            )

    after_row = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    after = analyze_release(conn, after_row, indexes)
    return {
        "编号": release_id,
        "发版单号": after["发版单号"],
        "修复项": actions,
        "修复动作": actions,
        "修复前差额": None,  # 由调用方在需要时填充
        "修复后差额": after["差额"],
        "一致": after["一致"],
        "对账": after,
    }


# ---------------------------------------------------------------- 汇总对账

def roster_with_instance_diff(conn) -> list[dict]:
    rows = rows_to_list(conn.execute(
        """
        SELECT a.name AS 应用, e.code AS 环境,
               v.version AS 名册版本,
               GROUP_CONCAT(i.version, ',') AS 实例版本们,
               SUM(CASE WHEN i.health='探针红' THEN 1 ELSE 0 END) AS 红灯数,
               COUNT(i.id) AS 实例数
        FROM app_env_versions v
        JOIN apps a ON a.id = v.app_id
        JOIN environments e ON e.id = v.env_id
        LEFT JOIN instances i ON i.app_id = v.app_id AND i.env_id = v.env_id
        GROUP BY v.app_id, v.env_id
        ORDER BY a.id, e.sort_order
        """
    ).fetchall())
    for row in rows:
        versions = {x for x in (row.get("实例版本们") or "").split(",") if x}
        roster = row.get("名册版本") or ""
        row["版本一致"] = bool(roster) and versions == {roster} and (row.get("红灯数") or 0) == 0
        row["名册实例一致"] = row["版本一致"]
    return rows


def build_reconcile(conn) -> dict:
    indexes = env_index(conn)
    raw = conn.execute("SELECT * FROM releases ORDER BY id").fetchall()
    details = [analyze_release(conn, r, indexes) for r in raw]

    flat_issues: list[dict] = []
    for d in details:
        for iss in d["差异"]:
            item = dict(iss)
            item["发版单编号"] = d["编号"]
            item["编号"] = d["编号"]
            item["发版单号"] = d["发版单号"]
            item["应用"] = d.get("应用")
            flat_issues.append(item)

    total = sum(d["差额"] for d in details)

    release_stats = {
        "申请数": conn.execute("SELECT COUNT(*) AS c FROM releases").fetchone()["c"],
        "已放行": conn.execute(
            "SELECT COUNT(*) AS c FROM releases WHERE status='已放行'"
        ).fetchone()["c"],
        "已回滚": conn.execute(
            "SELECT COUNT(*) AS c FROM releases WHERE status='已回滚'"
        ).fetchone()["c"],
        "在途": conn.execute(
            """
            SELECT COUNT(*) AS c FROM releases
            WHERE status IN ('已入闸','晋升中','已放行','回滚中')
            """
        ).fetchone()["c"],
    }
    promote_count = conn.execute("SELECT COUNT(*) AS c FROM promote_events").fetchone()["c"]
    valid_count = conn.execute(
        "SELECT COUNT(*) AS c FROM promote_events WHERE COALESCE(superseded,0)=0"
    ).fetchone()["c"]
    roster_rows = roster_with_instance_diff(conn)
    roster_instance_diff = sum(0 if r["版本一致"] else 1 for r in roster_rows)

    return {
        "真源": "发版单状态机",
        "发版统计": release_stats,
        "晋升事件数": promote_count,
        "有效晋升事件数": valid_count,
        "名册与实例": roster_rows,
        "对账明细": details,
        "发版单对账": details,
        "明细": details,
        "items": details,
        "差异明细": flat_issues,
        "差额明细": flat_issues,
        "差异列表": flat_issues,
        "差额": total,
        "差异数": total,
        "异常数": total,
        "问题总数": total,
        "一致": total == 0,
        "平账": total == 0,
        "对账结果": "平" if total == 0 else "不平",
        "名册实例差额": roster_instance_diff,
    }


# ---------------------------------------------------------------- 单据详情

def release_detail(conn, release_id: int) -> dict:
    row = get_release(conn, release_id)
    d = row_to_dict(row)
    raw = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    a = analyze_release(conn, raw)
    events = event_chain_view(conn, release_id)
    d["事件"] = events
    d["晋升事件"] = events
    d["事件列表"] = events
    d["全部事件"] = event_chain_view(conn, release_id, include_voided=True)
    d["重放环境"] = a["重放环境"]
    d["重放环境编号"] = a["重放环境编号"]
    d["重放状态"] = a["重放状态"]
    d["一致"] = a["一致"]
    d["差额"] = a["差额"]
    d["差异"] = a["差异"]
    d["异常"] = a["差异"]
    d["真源"] = "发版单状态机"
    return d
