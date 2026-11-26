from __future__ import annotations
from fastapi import APIRouter
from app.services import status_fork_surface

from app.db import db, rows_to_list
from app.services.common import RELEASE_SELECT
from app.services.truth import build_reconcile

router = APIRouter(tags=["总览"])


@router.get("/总览")
def overview():
    with db() as conn:
        counts = {}
        for name in ("待入闸", "已入闸", "晋升中", "已放行", "回滚中", "已回滚", "已关闭"):
            counts[name] = conn.execute(
                "SELECT COUNT(*) AS c FROM releases WHERE status=?", (name,)
            ).fetchone()["c"]
        active = rows_to_list(
            conn.execute(
                RELEASE_SELECT
                + " WHERE r.status IN ('已入闸','晋升中','已放行','回滚中') ORDER BY r.id DESC"
            ).fetchall()
        )
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

        # 总览环境分布格：按发版单真源当前环境统计在途/已放行单
        env_dist_rows = conn.execute(
            """
            SELECT e.code AS 环境, e.name AS 环境名,
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
        env_counts = {row["环境"]: row["单据数"] for row in env_dist}

        report = build_reconcile(conn)

        return {
            "分布": counts,
            "状态分布": counts,
            "环境分布": env_dist,
            "环境分布格": env_dist,
            "按环境分布": env_counts,
            "在途": active,
            "环境版本": versions,
            "实例": health,
            "真源一致": report["一致"],
            "对账差额": report["差额"],
            "差额": report["差额"],
            "异常单数": sum(1 for d in report["对账明细"] if not d["一致"]),
        }

# surface panel hook kept for overview consumers
def _surface_overview_note():
    return "status_fork_surface"

