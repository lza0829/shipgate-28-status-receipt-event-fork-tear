from __future__ import annotations
from fastapi import APIRouter

from app.db import db, rows_to_list
from app.services.common import RELEASE_SELECT
from app.services.truth import build_reconcile

router = APIRouter(tags=["总览"])


@router.get("/总览")
def overview():
    with db() as conn:
        report = build_reconcile(conn)
        details = report["对账明细"]
        by_id = {d["编号"]: d for d in details}

        counts = {}
        for name in ("待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭"):
            counts[name] = conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status=?", (name,)
            ).fetchone()["c"]
        # 已放行灯拆分：成立（证据同指）与缺口（假已放行）分开入账，
        # 缺口未清时总览不得当已对齐。
        counts["放行成立"] = report["发版统计"]["放行成立"]
        counts["放行缺口"] = report["发版统计"]["假已放行"]

        active = rows_to_list(
            conn.execute(
                RELEASE_SELECT
                + " WHERE r.status IN ('已入闸','晋升中','已放行','回滚中') ORDER BY r.id DESC"
            ).fetchall()
        )
        for row in active:
            d = by_id.get(row["编号"])
            if d:
                row["一致"] = d["一致"]
                row["差额"] = d["差额"]
                row["重放环境"] = d["重放环境"]
                row["假已放行"] = d["假已放行"]
                row["缺口未清"] = d["缺口未清"]
                row["缺口类型"] = d["缺口类型"]

        versions = rows_to_list(
            conn.execute(
                """
                SELECT a.name AS 应用, e.code AS 环境, e.name AS 环境名,
                       v.version AS 版本, v.updated_at AS 更新时间
                FROM app_env_versions v
                JOIN apps a ON a.id = v.app_id
                JOIN environments e ON e.id = v.env_id
                ORDER BY a.id, e.sort_order
                """
            ).fetchall()
        )
        health = rows_to_list(
            conn.execute(
                """
                SELECT i.id AS 编号, a.name AS 应用, e.code AS 环境, i.version AS 版本,
                       i.health AS 健康, i.release_id AS 发版单编号, i.updated_at AS 更新时间
                FROM instances i
                JOIN apps a ON a.id = i.app_id
                JOIN environments e ON e.id = i.env_id
                ORDER BY a.id, e.sort_order, i.id
                """
            ).fetchall()
        )

        # 总览环境分布格：按发版单真源当前环境统计在途/已放行单，
        # 每格钉缺口数与假已放行数，在途分布格不许藏撕裂。
        env_dist_rows = conn.execute(
            """
            SELECT e.id AS 环境编号, e.code AS 环境, e.name AS 环境名,
                   SUM(CASE WHEN r.status IN ('已入闸','晋升中','已放行','回滚中') THEN 1 ELSE 0 END) AS 在途数,
                   SUM(CASE WHEN r.status='已放行' THEN 1 ELSE 0 END) AS 已放行数,
                   COUNT(r.id) AS 单据数
            FROM environments e
            LEFT JOIN releases r ON r.current_env_id = e.id
            GROUP BY e.id
            ORDER BY e.sort_order
            """
        ).fetchall()
        env_dist = rows_to_list(env_dist_rows)
        for cell in env_dist:
            cell["缺口数"] = sum(
                1 for d in details
                if d["真源环境编号"] == cell["环境编号"] and d["缺口未清"]
            )
            cell["假已放行数"] = sum(
                1 for d in details
                if d["真源环境编号"] == cell["环境编号"] and d["假已放行"]
            )
        env_counts = {row["环境"]: row["单据数"] for row in env_dist}

        return {
            "分布": counts,
            "状态分布": counts,
            "环境分布": env_dist,
            "环境分布格": env_dist,
            "按环境分布": env_counts,
            "在途": active,
            "环境版本": versions,
            "实例": health,
            "缺口": report["缺口"],
            "缺口数": report["缺口数"],
            "缺口未清": report["缺口未清"],
            "假已放行数": report["假已放行数"],
            "真源一致": report["一致"],
            "对账差额": report["差额"],
            "差额": report["差额"],
            "异常单数": sum(1 for d in details if not d["一致"]),
        }
