from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import db
from app.services.common import (
    RELEASE_SELECT,
    assert_app_enabled,
    audit,
    env_by_code,
    get_release,
    get_setting,
    next_serial,
    now_str,
)
from app.services.truth import release_detail, repair_release

router = APIRouter(tags=["发版单"])


class ReleaseIn(BaseModel):
    应用编号: int
    目标版本: str = Field(min_length=1)
    制品摘要: str = ""
    金丝雀比例: int | None = None
    备注: str = ""


class PipelineIn(BaseModel):
    流水线: str


class ManualStatusIn(BaseModel):
    状态: str | None = None
    status: str | None = None
    当前环境: str | int | None = None
    环境: str | int | None = None
    current_env: str | int | None = None
    current_env_id: int | None = None
    备注: str = ""
    note: str | None = None
    状态版本: int | None = None
    state_rev: int | None = None

@router.get("/发版单")
def list_releases():
    with db() as conn:
        from app.db import rows_to_list
        from app.services.truth import analyze_release

        rows = rows_to_list(conn.execute(RELEASE_SELECT + " ORDER BY r.id DESC").fetchall())
        for row in rows:
            raw = conn.execute("SELECT * FROM releases WHERE id=?", (row["编号"],)).fetchone()
            a = analyze_release(conn, raw)
            row["一致"] = a["一致"]
            row["差额"] = a["差额"]
            row["重放环境"] = a["重放环境"]
        return rows


@router.get("/发版单/{release_id}")
def one_release(release_id: int):
    with db() as conn:
        return release_detail(conn, release_id)


@router.get("/发版单/{release_id}/详情", include_in_schema=False)
def one_release_detail_alias(release_id: int):
    with db() as conn:
        return release_detail(conn, release_id)


@router.post("/发版单")
def create_release(body: ReleaseIn):
    with db() as conn:
        assert_app_enabled(conn, body.应用编号)
        ratio = body.金丝雀比例
        if ratio is None:
            ratio = int(get_setting(conn, "金丝雀默认比例", "10") or "10")
        if ratio < 0 or ratio > 100:
            raise HTTPException(400, "金丝雀比例须在 0 到 100")
        serial = next_serial(conn)
        now = now_str()
        cur = conn.execute(
            """
            INSERT INTO releases(
              serial, app_id, target_version, artifact_digest, status, pipeline_status,
              canary_ratio, note, created_at, state_rev, state_advanced_at
            ) VALUES (?, ?, ?, ?, '待入闸', '未回执', ?, ?, ?, 0, ?)
            """,
            (serial, body.应用编号, body.目标版本, body.制品摘要, ratio, body.备注, now, now),
        )
        rid = cur.lastrowid
        audit(conn, "发版单", rid, "申请发版", serial)
        return release_detail(conn, rid)


@router.post("/发版单/{release_id}/入闸")
def admit(release_id: int):
    with db() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        if r["status"] != "待入闸":
            raise HTTPException(400, "仅待入闸可入闸")
        assert_app_enabled(conn, r["app_id"])
        must_green = get_setting(conn, "入闸须流水线绿", "是") == "是"
        if must_green and r["pipeline_status"] != "绿":
            raise HTTPException(400, "流水线未绿，禁止入闸")
        if not r["artifact_digest"]:
            raise HTTPException(400, "缺少制品摘要，禁止入闸")
        active = conn.execute(
            """
            SELECT id FROM releases
            WHERE app_id=? AND id!=? AND status IN ('已入闸','晋升中','已放行','回滚中')
            """,
            (r["app_id"], release_id),
        ).fetchone()
        if active:
            raise HTTPException(400, "同应用已有在途发版单，禁止并行入闸")
        test = conn.execute("SELECT id FROM environments WHERE code='测'").fetchone()
        now = now_str()
        conn.execute(
            """
            UPDATE releases
               SET status='已入闸', admitted_at=?, current_env_id=?,
                   state_rev=state_rev+1, state_advanced_at=?
             WHERE id=?
            """,
            (now, test["id"], now, release_id),
        )
        audit(conn, "发版单", release_id, "入闸", r["serial"])
        return release_detail(conn, release_id)


@router.post("/发版单/{release_id}/流水线")
def set_pipeline(release_id: int, body: PipelineIn):
    if body.流水线 not in ("未回执", "绿", "红"):
        raise HTTPException(400, "流水线状态非法")
    with db() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        conn.execute(
            "UPDATE releases SET pipeline_status=? WHERE id=?",
            (body.流水线, release_id),
        )
        audit(conn, "发版单", release_id, "流水线回执", body.流水线)
        return release_detail(conn, release_id)


# ------------------------------------------------------------ 手改状态（唯一真源约束下）

def _resolve_env(conn, value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        row = conn.execute("SELECT id FROM environments WHERE id=?", (value,)).fetchone()
        if not row:
            raise HTTPException(400, f"环境编号不存在：{value}")
        return row["id"]
    s = str(value)
    if s.isdigit():
        row = conn.execute("SELECT id FROM environments WHERE id=?", (int(s),)).fetchone()
        if row:
            return row["id"]
    return env_by_code(conn, s)["id"]


def _manual_status(release_id: int, body: ManualStatusIn):
    new_status = body.状态 or body.status
    note_text = body.备注 or body.note or "手改状态"
    with db() as conn:
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        rev = body.状态版本 if body.状态版本 is not None else body.state_rev
        if rev is not None and rev != r["state_rev"]:
            raise HTTPException(409, "状态版本已变化，请刷新后重试")

        sets, params = [], []
        if new_status is not None:
            if new_status not in (
                "待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭"
            ):
                raise HTTPException(400, "状态非法")
            sets.append("status=?")
            params.append(new_status)
            if new_status == "已放行":
                sets.append("released_at=COALESCE(released_at, ?)")
                params.append(now_str())
            if new_status == "已回滚":
                sets.append("rolled_back_at=COALESCE(rolled_back_at, ?)")
                params.append(now_str())
            if new_status == "已入闸":
                sets.append("admitted_at=COALESCE(admitted_at, ?)")
                params.append(now_str())

        env_value = (
            body.当前环境 if body.当前环境 is not None
            else body.环境 if body.环境 is not None
            else body.current_env if body.current_env is not None
            else body.current_env_id
        )
        if env_value is not None:
            env_id = _resolve_env(conn, env_value)
            sets.append("current_env_id=?")
            params.append(env_id)

        if not sets:
            raise HTTPException(400, "未提供可更新字段")

        now = now_str()
        sets.append("state_rev=state_rev+1")
        sets.append("state_advanced_at=?")
        params.append(now)
        params.append(release_id)
        conn.execute(f"UPDATE releases SET {', '.join(sets)} WHERE id=?", params)
        audit(conn, "发版单", release_id, "手改状态", f"{new_status or r['status']}；{note_text}")

        # 手改后立刻按唯一真源自收敛，避免与晋升流水长期两套账。
        repaired = repair_release(conn, release_id)
        if repaired["修复项"]:
            audit(conn, "对账", release_id, "手改后纠偏", "；".join(repaired["修复项"]))
        detail = release_detail(conn, release_id)
        detail["纠偏"] = repaired
        return detail


@router.patch("/发版单/{release_id}")
def patch_release(release_id: int, body: ManualStatusIn):
    return _manual_status(release_id, body)


@router.api_route("/发版单/{release_id}/状态", methods=["POST", "PATCH", "PUT"])
def manual_status(release_id: int, body: ManualStatusIn):
    return _manual_status(release_id, body)


@router.post("/发版单/{release_id}/手改状态", include_in_schema=False)
def manual_status_alias(release_id: int, body: ManualStatusIn):
    return _manual_status(release_id, body)
