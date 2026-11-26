from __future__ import annotations
from fastapi import APIRouter, Query

from app.db import db
from app.services.truth import event_chain_view

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


@router.get("/发版单/{release_id}/事件")
def list_release_events(release_id: int, 含作废: bool = Query(False)):
    return _list(release_id, 含作废)


@router.get("/events", include_in_schema=False)
def list_events_en(release_id: int | None = Query(None), include_voided: bool = Query(False)):
    return _list(release_id, include_voided)
