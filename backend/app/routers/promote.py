from __future__ import annotations
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from app.services import status_fork_surface

from app.db import db
from app.services.common import (
    active_release_window,
    audit,
    env_by_code,
    get_setting,
    now_str,
    ordered_envs,
    set_app_env_version,
    upsert_instance,
)
from app.services.truth import add_event, next_seq, release_detail

router = APIRouter(tags=["晋升"])


class PromoteIn(BaseModel):
    目标环境: str | None = None
    环境: str | None = None
    环境代号: str | None = None
    target_env: str | None = None
    备注: str = ""
    note: str | None = None


def _pick_env(body: PromoteIn) -> str:
    env = body.目标环境 or body.环境 or body.环境代号 or body.target_env
    if not env:
        raise HTTPException(422, "缺少目标环境")
    return env


def _pick_note(body: PromoteIn) -> str:
    return body.备注 or body.note or ""


def _promote(release_id: int, target_code: str, note_text: str):
    with db() as conn:  # BEGIN IMMEDIATE：并发晋升在此串行
        r = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        if not r:
            raise HTTPException(404, "发版单不存在")
        if r["status"] not in ("已入闸", "晋升中"):
            raise HTTPException(400, "当前状态不可晋升")
        to_env = env_by_code(conn, target_code)
        envs = ordered_envs(conn)
        codes = [e["code"] for e in envs]
        if target_code not in codes:
            raise HTTPException(400, "目标环境非法")
        cur_env = None
        if r["current_env_id"]:
            cur_env = conn.execute(
                "SELECT * FROM environments WHERE id=?", (r["current_env_id"],)
            ).fetchone()
        allow_skip = get_setting(conn, "允许跳级", "否") == "是"
        if cur_env:
            cur_idx = codes.index(cur_env["code"])
            to_idx = codes.index(target_code)
            if to_idx <= cur_idx:
                raise HTTPException(400, "只能向更高环境晋升")
            if not allow_skip and to_idx != cur_idx + 1:
                raise HTTPException(400, "禁止跳级，须逐级晋升")
        else:
            if target_code != "测":
                raise HTTPException(400, "未落地时只能先入测")

        win = active_release_window(conn, to_env["id"])
        hard = get_setting(conn, "维护窗硬拒", "是") == "是"
        if hard and not win:
            raise HTTPException(400, "目标环境放行窗已关，禁止晋升")

        now = now_str()
        seq = next_seq(conn, release_id)
        new_status = "已放行" if target_code == "产" else "晋升中"
        released_at = now if target_code == "产" else r["released_at"]

        # 事件写入与状态推进在同一事务：任何一步失败整体回滚，不会再留半截双账。
        add_event(
            conn, release_id, r["current_env_id"], to_env["id"],
            note=note_text, origin="正常", seq=seq, created_at=now,
        )
        cur = conn.execute(
            """
            UPDATE releases
               SET status=?, current_env_id=?, released_at=?,
                   state_rev=state_rev+1, state_advanced_at=?
             WHERE id=? AND state_rev=? AND status IN ('已入闸','晋升中')
            """,
            (new_status, to_env["id"], released_at, now, release_id, r["state_rev"]),
        )
        if cur.rowcount != 1:
            # 并发者已经推进过状态：回滚刚写入的事件，调用方刷新后重试。
            raise HTTPException(409, "发版单状态已被并发晋升/手改，请刷新后重试")

        set_app_env_version(conn, r["app_id"], to_env["id"], r["target_version"])
        upsert_instance(conn, r["app_id"], to_env["id"], r["target_version"], "探针绿", release_id)
        audit(conn, "晋升", release_id, f"晋升到{target_code}", f"序号{seq}；{note_text}".strip("；"))
        return release_detail(conn, release_id)


@router.post("/发版单/{release_id}/晋升")
def promote(release_id: int, body: PromoteIn):
    return _promote(release_id, _pick_env(body), _pick_note(body))


# 契约别名：部分夹具可能以英文路径/字段发起晋升
@router.post("/releases/{release_id}/promote", include_in_schema=False)
def promote_alias(release_id: int, body: PromoteIn):
    return _promote(release_id, _pick_env(body), _pick_note(body))
