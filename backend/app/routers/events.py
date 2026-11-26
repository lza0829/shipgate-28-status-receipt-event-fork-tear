from __future__ import annotations
from fastapi import APIRouter, Query

from app.db import db
from app.services.truth import build_reconcile, event_chain_view

router = APIRouter(tags=["晋升事件"])


def _list(release_id: int | None, include_voided: bool):
    with db() as conn:
        if release_id is not None:
            return event_chain_view(conn, release_id, include_voided=include_voided)
        sql = """
            SELECT p.id AS 编号, p.release_id AS 发版单编号, p.seq AS 序号, p.seq AS seq,
                   ef.code AS 起始环境, et.code AS 目标环境,
                   p.decision AS 裁决, p.created_at AS 时间, p.created_at AS created_at,
                   p.note AS 备注, p.origin AS 来源,
                   COALESCE(p.superseded,0) AS 作废
            FROM promote_events p
            LEFT JOIN environments ef ON ef.id = p.from_env_id
            JOIN environments et ON et.id = p.to_env_id
        """
        where = []
        if not include_voided:
            where.append("COALESCE(p.superseded,0)=0")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.release_id, CASE WHEN p.seq IS NULL THEN 1 ELSE 0 END, p.seq, p.id"
        from app.db import rows_to_list
        return rows_to_list(conn.execute(sql).fetchall())


@router.get("/晋升事件")
def list_events(
    发版单编号: int | None = Query(None),
    release_id: int | None = Query(None),
    含作废: bool = Query(False),
    all: bool = Query(False),
):
    rid = 发版单编号 if 发版单编号 is not None else release_id
    return _list(rid, 含作废 or all)


@router.get("/晋升事件/对照")
def events_cross_read():
    """晋升事件流环境链 × 单态 × 已放行灯 对照：每单一行，缺口钉在链上。"""
    with db() as conn:
        report = build_reconcile(conn)
        rows = []
        for d in report["对账明细"]:
            rows.append({
                "编号": d["编号"],
                "发版单号": d["发版单号"],
                "应用": d.get("应用"),
                "状态": d["真源状态"],
                "真源环境": d["真源环境"],
                "重放环境": d["重放环境"],
                "环境链": d["环境链"],
                "事件数": d["事件数"],
                "事件序号": d["事件序号"],
                "序号连续": d["序号连续"],
                "名册版本": d["名册版本"],
                "目标版本": d.get("目标版本"),
                "已放行灯": d["已放行灯"]["亮"],
                "放行成立": d["放行成立"],
                "假已放行": d["假已放行"],
                "缺口未清": d["缺口未清"],
                "缺口类型": d["缺口类型"],
                "差额": d["差额"],
            })
        return {
            "真源": "发版单状态机",
            "对照": rows,
            "行": rows,
            "缺口数": sum(1 for r in rows if r["缺口未清"]),
            "缺口未清": any(r["缺口未清"] for r in rows),
        }


@router.get("/发版单/{release_id}/事件")
def list_release_events(release_id: int, 含作废: bool = Query(False)):
    return _list(release_id, 含作废)


@router.get("/events", include_in_schema=False)
def list_events_en(release_id: int | None = Query(None), include_voided: bool = Query(False)):
    return _list(release_id, include_voided)
