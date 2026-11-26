import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'

function Lamp({ lamp, valid }) {
  if (!lamp) return <span className="lamp lamp-off">未放行</span>
  if (valid) return <span className="lamp lamp-on">已放行 · 成立</span>
  return <span className="lamp lamp-fake">已放行 · 缺口未清</span>
}

export default function ReleaseDetail() {
  const { id } = useParams()
  const [d, setD] = useState(null)
  const [envs, setEnvs] = useState([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [target, setTarget] = useState('预')
  const [manualStatus, setManualStatus] = useState('已放行')

  const load = useCallback(async () => {
    setErr('')
    try {
      const [detail, envRows] = await Promise.all([
        api(`/发版单/${id}`),
        api('/环境').catch(() => []),
      ])
      setD(detail)
      setEnvs(envRows || [])
    } catch (e) { setErr(e.message) }
  }, [id])

  useEffect(() => { load() }, [load])

  const act = async (fn, okText) => {
    setErr(''); setMsg('')
    try {
      const out = await fn()
      setMsg(okText || '操作完成')
      if (out && out.修复 && out.修复.修复项 && out.修复.修复项.length) {
        setMsg(`已纠偏：${out.修复.修复项.join('；')}`)
      }
      await load()
    } catch (e) { setErr(e.message) }
  }

  if (err && !d) return <div className="panel err">{err}</div>
  if (!d) return <div className="panel">加载中</div>

  const canPromote = ['已入闸', '晋升中'].includes(d.状态)
  const canAdmit = d.状态 === '待入闸'
  const lamp = d.已放行灯 || { 亮: d.状态 === '已放行', 成立: false, 证据: {} }
  const ev = lamp.证据 || {}
  const chain = d.环境链 || []
  const envOrder = envs.length ? envs.map((e) => e.代号) : Array.from(new Set([d.基线环境, ...chain, d.当前环境, d.重放环境].filter(Boolean)))
  const audits = d.审计 || []

  return (
    <div className="panel">
      <div className="detail-head">
        <h2>发版单详情 · {d.发版单号}</h2>
        <Link to="/发版单">← 返回发版单列表</Link>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <p className="ok-msg">{msg}</p>}

      <div className="grid">
        <div className="stat"><div className="n">{d.状态}</div><div className="l">状态机状态</div></div>
        <div className="stat"><div className="n">{d.当前环境 || '-'}</div><div className="l">当前环境（真源）</div></div>
        <div className="stat"><div className="n">{d.重放环境 || '-'}</div><div className="l">事件重放环境</div></div>
        <div className="stat"><div className="n">{d.目标版本}</div><div className="l">目标版本</div></div>
        <div className="stat"><div className="n">{d.state_rev ?? d.状态版本}</div><div className="l">状态版本（乐观锁）</div></div>
        <div className={`stat ${d.一致 ? '' : 'stat-bad'}`}>
          <div className="n">{d.一致 ? '一致' : `差额 ${d.差额}`}</div><div className="l">真源/事件/名册</div>
        </div>
        <div className={`stat ${lamp.亮 ? (lamp.成立 ? 'stat-ok' : 'stat-bad') : ''}`}>
          <div className="n"><Lamp lamp={lamp.亮} valid={lamp.成立} /></div>
          <div className="l">已放行灯（单态∪事件∪对账∪审计）</div>
        </div>
      </div>

      <h3>已放行灯 × 事件环境链 · 同屏对照</h3>
      <div className="crossread">
        <div className="crossread-col">
          <h4>单态（状态机）</h4>
          <div className="crossread-line">状态：<b>{d.状态}</b></div>
          <div className="crossread-line">当前环境：<b>{d.当前环境 || '-'}</b></div>
          <div className="crossread-line">推进戳：{d.状态机推进戳 || '-'}</div>
          <div className="crossread-line">状态版本：{d.state_rev ?? d.状态版本}</div>
        </div>
        <div className="crossread-col">
          <h4>晋升事件流 · 环境链</h4>
          <div className="chain">
            {envOrder.map((code, i) => {
              const reached = chain.includes(code)
              const isTruth = d.当前环境 === code
              const isReplay = d.重放环境 === code
              return (
                <React.Fragment key={code}>
                  {i > 0 && <span className="chain-arrow">→</span>}
                  <span className={`chain-env ${reached ? 'reached' : ''} ${isTruth ? 'truth' : ''} ${isReplay ? 'replay' : ''}`}>
                    {code}
                    {isTruth && <em>单态</em>}
                    {isReplay && <em>重放</em>}
                  </span>
                </React.Fragment>
              )
            })}
          </div>
          <div className="crossread-line">事件序号：{(d.事件序号 || []).join(',') || '-'}（{d.序号连续 ? '连续' : '断号'}）</div>
          <div className="crossread-line">重放环境：<b>{d.重放环境 || '-'}</b>（重放状态 {d.重放状态 || '-'}）</div>
        </div>
        <div className="crossread-col">
          <h4>名册旁读（跨环）</h4>
          <div className="crossread-line">名册@{d.当前环境 || '-'}：<b>{d.名册版本 || '空'}</b>（目标 {d.目标版本}）</div>
          <div className="chain">
            {(d.名册旁读 || []).map((r) => (
              <span key={r.环境} className={`chain-env ${r.环境 === d.当前环境 ? 'truth' : ''}`}>
                {r.环境}·{r.版本 || '空'}
              </span>
            ))}
          </div>
        </div>
        <div className="crossread-col">
          <h4>审计腿</h4>
          <div className="crossread-line">放行证据：{d.审计放行证据 ? <span className="badge ok">有</span> : <span className="badge warn">无</span>}</div>
          <div className="crossread-line">本单审计 {audits.length} 条（见下表）</div>
          <div className="crossread-line">灯判定：{lamp.亮 ? (lamp.成立 ? '四证同指，成立' : '证据未同指，钉缺口') : '未点亮'}</div>
        </div>
      </div>

      {d.缺口未清 && (
        <div className="diff-box">
          <h3>缺口（{d.差额}）· 假已放行钉住，纠回或整笔退</h3>
          <ul>
            {(d.差异 || []).map((x, i) => (
              <li key={i}><span className="badge bad">{x.类型}</span> {x.说明}</li>
            ))}
          </ul>
          <button type="button" onClick={() => act(
            () => api(`/发版单/${id}/纠偏`, { method: 'POST', body: '{}' }),
            '纠偏完成，已收敛到发版单状态机真源',
          )}>缺事件纠偏 / 一键纠偏</button>
        </div>
      )}

      <table className="kv">
        <tbody>
          <tr><th>应用</th><td>{d.应用}（{d.负责人}）</td><th>流水线</th><td>{d.流水线}</td></tr>
          <tr><th>制品摘要</th><td>{d.制品摘要 || '-'}</td><th>金丝雀比例</th><td>{d.金丝雀比例}%</td></tr>
          <tr><th>申请时间</th><td>{d.申请时间}</td><th>入闸时间</th><td>{d.入闸时间 || '-'}</td></tr>
          <tr><th>状态机推进戳</th><td>{d.状态机推进戳 || '-'}</td><th>放行时间</th><td>{d.放行时间 || '-'}</td></tr>
        </tbody>
      </table>

      <h3>操作（晋升入口）</h3>
      <div className="row">
        {canAdmit && (
          <button type="button" onClick={() => act(
            () => api(`/发版单/${id}/入闸`, { method: 'POST', body: '{}' }), '已入闸')}>入闸</button>
        )}
        <button type="button" className="secondary" onClick={() => act(
          () => api(`/发版单/${id}/流水线`, { method: 'POST', body: JSON.stringify({ 流水线: '绿' }) }), '流水线已回执绿')}>
          流水线绿
        </button>
        <button type="button" className="danger" onClick={() => act(
          () => api(`/发版单/${id}/流水线`, { method: 'POST', body: JSON.stringify({ 流水线: '红' }) }), '流水线已回执红')}>
          流水线红
        </button>
        {canPromote && (
          <>
            <label>目标环境
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                <option value="预">预</option>
                <option value="产">产</option>
                <option value="测">测</option>
              </select>
            </label>
            <button type="button" onClick={() => act(
              () => api(`/发版单/${id}/晋升`, { method: 'POST', body: JSON.stringify({ 目标环境: target }) }),
              `晋升请求完成：${target}`,
            )}>晋升</button>
          </>
        )}
        <label>手改状态
          <select value={manualStatus} onChange={(e) => setManualStatus(e.target.value)}>
            {['待入闸', '已入闸', '晋升中', '已放行', '回滚中', '已回滚', '已关闭'].map((s) => <option key={s}>{s}</option>)}
          </select>
        </label>
        <button type="button" className="danger" onClick={() => act(
          () => api(`/发版单/${id}/状态`, { method: 'POST', body: JSON.stringify({ 状态: manualStatus }) }),
          '手改完成并已按唯一真源自收敛',
        )}>手改状态并收敛</button>
      </div>

      <h3>事件列表（晋升事件流 · 序号连续）</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>序号</th><th>时间</th><th>起始环境</th><th>目标环境</th><th>裁决</th><th>来源</th><th>备注</th></tr></thead>
          <tbody>
            {(d.事件 || []).length === 0 && <tr><td colSpan="7" className="muted">暂无晋升事件（入闸落地测不产生晋升事件）</td></tr>}
            {(d.事件 || []).map((e) => (
              <tr key={e.编号}>
                <td>{e.序号}</td><td>{e.时间}</td>
                <td>{e.起始环境 || '-'}</td><td>{e.目标环境}</td><td>{e.裁决}</td>
                <td>{e.来源 === '补录' ? <span className="badge warn">补录</span> : e.来源}</td>
                <td>{e.备注}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>挂接实例（挂接行）</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>环境</th><th>版本</th><th>健康</th><th>更新时间</th></tr></thead>
          <tbody>
            {(d.挂接实例 || []).map((x) => (
              <tr key={x.编号}>
                <td>{x.环境}（{x.环境名}）</td><td>{x.版本}</td>
                <td>{x.健康 === '探针绿' ? <span className="badge ok">{x.健康}</span> : <span className="badge bad">{x.健康}</span>}</td>
                <td>{x.更新时间}</td>
              </tr>
            ))}
            {(d.挂接实例 || []).length === 0 && <tr><td colSpan="4" className="muted">暂无实例挂接到本单</td></tr>}
          </tbody>
        </table>
      </div>

      <h3>本单审计</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>类别</th><th>动作</th><th>备注</th></tr></thead>
          <tbody>
            {audits.map((a) => (
              <tr key={a.编号}><td>{a.时间}</td><td>{a.类别}</td><td>{a.动作}</td><td>{a.备注}</td></tr>
            ))}
            {audits.length === 0 && <tr><td colSpan="4" className="muted">暂无审计记录</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
