from __future__ import annotations
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.db import db
from app.services.common import audit
from app.services.truth import build_reconcile, repair_release

router = APIRouter(tags=["对账"])


class RepairIn(BaseModel):
    发版单编号: int | None = None
    编号: int | None = None
    release_id: int | None = None
    id: int | None = None
    纠偏: bool | None = None
    repair: bool | None = None


@router.get("/对账")
def reconcile():
    with db() as conn:
        return build_reconcile(conn)


@router.get("/reconcile", include_in_schema=False)
def reconcile_en():
    with db() as conn:
        return build_reconcile(conn)


@router.get("/对账/重放", include_in_schema=False)
def reconcile_replay():
    with db() as conn:
        return build_reconcile(conn)


@router.post("/对账/重放", include_in_schema=False)
def reconcile_replay_repair(request: Request, body: RepairIn | None = None):
    # 选定真源为发版单状态机：所谓“重放纠偏”同样收敛回单态真源
    return _repair(_target_id(body, request))


def _target_id(body: RepairIn | None, request: Request | None = None) -> int | None:
    if body is not None:
        tid = body.发版单编号 or body.编号 or body.release_id or body.id
        if tid is not None:
            return tid
    if request is not None:
        qp = request.query_params
        raw = qp.get("发版单编号") or qp.get("编号") or qp.get("release_id") or qp.get("id")
        if raw:
            try:
                return int(raw)
            except ValueError:
                return None
    return None


def _repair(target: int | None):
    with db() as conn:
        if target is not None:
            before = build_reconcile(conn)
            before_row = next((d for d in before["对账明细"] if d["编号"] == target), None)
            before_diff = before_row["差额"] if before_row else None
            result = repair_release(conn, target)
            result["修复前差额"] = before_diff
            if result["修复项"]:
                audit(conn, "对账", target, "纠偏", "；".join(result["修复项"]))
            report = build_reconcile(conn)
            return {"修复": result, "对账": report, **report}

        before = build_reconcile(conn)
        repaired = []
        for d in before["对账明细"]:
            if d["差额"]:
                res = repair_release(conn, d["编号"])
                res["修复前差额"] = d["差额"]
                repaired.append(res)
                if res["修复项"]:
                    audit(conn, "对账", d["编号"], "批量纠偏", "；".join(res["修复项"]))
        report = build_reconcile(conn)
        return {
            "修复": repaired,
            "修复单数": len(repaired),
            "对账": report,
            **report,
        }


@router.post("/对账/纠偏")
def repair_all(request: Request, body: RepairIn | None = None):
    return _repair(_target_id(body, request))


@router.post("/对账/修复", include_in_schema=False)
def repair_all_alias_fix(request: Request, body: RepairIn | None = None):
    return _repair(_target_id(body, request))


@router.post("/对账/校正", include_in_schema=False)
def repair_all_alias_align(request: Request, body: RepairIn | None = None):
    return _repair(_target_id(body, request))


@router.post("/对账", include_in_schema=False)
def post_reconcile(request: Request, body: RepairIn | None = None):
    # 允许把 POST /对账 直接当作“执行并纠偏”入口
    return _repair(_target_id(body, request))


@router.post("/纠偏", include_in_schema=False)
def repair_root(request: Request, body: RepairIn | None = None):
    return _repair(_target_id(body, request))


@router.post("/reconcile/repair", include_in_schema=False)
def repair_english(request: Request, body: RepairIn | None = None):
    return _repair(_target_id(body, request))


@router.post("/发版单/{release_id}/纠偏")
def repair_one(release_id: int):
    return _repair(release_id)


@router.post("/发版单/{release_id}/修复", include_in_schema=False)
def repair_one_alias(release_id: int):
    return _repair(release_id)


@router.post("/releases/{release_id}/repair", include_in_schema=False)
def repair_one_english(release_id: int):
    return _repair(release_id)

