# 发版闸（Shipgate）

骨架：发版申请入闸 → 环境晋升裁决 → 放行/回滚窗 → 发布结果对账

- 前端 http://127.0.0.1:6800
- API http://127.0.0.1:11800
- 数据库环境变量 `SHIPGATE_DB`（容器内默认 `/data/shipgate.db`）

```bash
docker compose up -d --build
```

## 晋升结果唯一真源：发版单状态机（方案 A）

晋升结果只认 `releases.status + current_env_id + state_rev` 这一本账：

- **同笔事务**：晋升时事件插入（`promote_events`，每单稠密 `seq`）、状态推进
  （`state_rev` CAS + `state_advanced_at` 推进戳）、名册/实例投影、审计写入在同一个
  `BEGIN IMMEDIATE` 工作单元内提交，任何一步失败整体回滚。
- **并发安全**：SQLite `busy_timeout=30s` + 立即写锁串行化，状态更新带
  `WHERE state_rev=?` 乐观锁；并发同目标晋升恰好一单成功，其余 400/409，不会产生双事件。
- **事件只用于核验**：对账按事件链重放环境，仅与真源比对产出类型化差异
  （`事件缺失 / 事件越位 / 序号断号 / 状态环境不一致 / 名册版本不一致`），
  **绝不用重放盖写单态**；名册 `app_env_versions` 是下游投影，只按发版单真源对齐。
- **拧花可纠**：`POST /api/对账/纠偏`（全部）或 `POST /api/发版单/{id}/纠偏`（单单）
  把当前环境、事件链（补录/作废/重建/重整序号）、名册版本收敛回状态机真源，
  纠偏过程写审计，重复执行幂等。手改状态接口
  `POST /api/发版单/{id}/状态`（支持 `状态版本` 乐观锁）提交后在同事务内立即自收敛。
- 回退时段写闸与总览环境分布格维持各自原语义，未并入晋升真源。

关键读面均带真源/重放/差额字段：`GET /api/发版单/{id}`（详情含全部事件）、
`GET /api/晋升事件`（`?发版单编号=&含作废=true`）、`GET /api/对账`
（别名 `/api/reconcile`、`/api/对账/重放`）、`GET /api/总览`（环境分布格、真源一致）、
`GET /api/审计`（类别/动作/关联编号/关键词/时间区间条件）。前端导航含
发版单详情、晋升、事件列表、对账、总览、审计查询的串读页面。

## 本地开发与验证

```bash
# 后端（依赖 fastapi/uvicorn/pytest/httpx）
cd backend
python3 -m pytest tests/ -q          # 13 个用例：黄金夹具/缺事件/越位/半截/名册/并发/手改/审计

# 构造四类拧花夹具库（平账、缺事件、事件越位、半截单态、名册拧花）
python3 scripts/make_fixtures.py /tmp/fixture.db
SHIPGATE_DB=/tmp/fixture.db uvicorn app.main:app --port 11800
#   GET  /api/对账        -> 差额 4，四类差异各 1
#   POST /api/对账/纠偏   -> 修复 4 单，最终差额 0；再次调用修复 0 单（幂等）

# 前端
cd frontend && npm install && npm run dev    # 或 npm run build
```

