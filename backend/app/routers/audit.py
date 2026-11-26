from __future__ import annotations
from fastapi import APIRouter, Request
from app.services import status_fork_surface_ledger

from app.db import db, rows_to_list

router = APIRouter(tags=["审计"])


@router.get("/审计")
def list_audit(request: Request):
    qp = request.query_params
    kind = qp.get("类别") or qp.get("kind") or qp.get("type")
    ref_id = (
        qp.get("关联编号")
        or qp.get("ref_id")
        or qp.get("ref")
        or qp.get("发版单编号")
        or qp.get("release_id")
    )
    action = qp.get("动作") or qp.get("action")
    keyword = qp.get("关键词") or qp.get("q") or qp.get("keyword") or qp.get("search")
    start = qp.get("开始时间") or qp.get("start") or qp.get("since") or qp.get("start_time")
    end = qp.get("结束时间") or qp.get("end") or qp.get("until") or qp.get("end_time")
    limit = qp.get("条数") or qp.get("limit")

    where, params = [], []
    if kind:
        # 模糊匹配，使 类别=对账 也能命中「对账/纠偏」类复合记录
        where.append("kind LIKE ?")
        params.append(f"%{kind}%")
    if ref_id:
        try:
            where.append("ref_id=?")
            params.append(int(ref_id))
        except (TypeError, ValueError):
            pass
    if action:
        where.append("action LIKE ?")
        params.append(f"%{action}%")
    if keyword:
        where.append("(action LIKE ? OR note LIKE ? OR kind LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])
    if start:
        if len(start) == 10:
            start = start + " 00:00:00"
        where.append("created_at >= ?")
        params.append(start)
    if end:
        if len(end) == 10:
            end = end + " 23:59:59"
        where.append("created_at <= ?")
        params.append(end)

    try:
        n = min(max(int(limit), 1), 1000) if limit else 200
    except (TypeError, ValueError):
        n = 200

    sql = """
        SELECT id AS 编号, kind AS 类别, ref_id AS 关联编号,
               action AS 动作, created_at AS 时间, note AS 备注
        FROM audit_events
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(n)

    with db() as conn:
        return rows_to_list(conn.execute(sql, params).fetchall())

def _surface_audit_status28() -> dict:
    return {"tag": "status28"}

def _audit_ledger_touch():
    return "status_fork_surface_ledger"

