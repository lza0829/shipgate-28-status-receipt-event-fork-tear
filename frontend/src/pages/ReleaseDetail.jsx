import React, { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'

export default function ReleaseDetail() {
  const { id } = useParams()
  const [d, setD] = useState(null)
  const [audits, setAudits] = useState([])
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [target, setTarget] = useState('预')
  const [manualStatus, setManualStatus] = useState('已放行')

  const load = useCallback(async () => {
    setErr('')
    try {
      const detail = await api(`/发版单/${id}`)
      setD(detail)
      const qs = new URLSearchParams({ 关联编号: String(id) }).toString()
      const au = await api(`/审计?${qs}`)
      setAudits(au)
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
      </div>

      <table className="kv">
        <tbody>
          <tr><th>应用</th><td>{d.应用}（{d.负责人}）</td><th>流水线</th><td>{d.流水线}</td></tr>
          <tr><th>制品摘要</th><td>{d.制品摘要 || '-'}</td><th>金丝雀比例</th><td>{d.金丝雀比例}%</td></tr>
          <tr><th>申请时间</th><td>{d.申请时间}</td><th>入闸时间</th><td>{d.入闸时间 || '-'}</td></tr>
          <tr><th>状态机推进戳</th><td>{d.状态机推进戳 || '-'}</td><th>放行时间</th><td>{d.放行时间 || '-'}</td></tr>
        </tbody>
      </table>

      {!d.一致 && (
        <div className="diff-box">
          <h3>对账差异（{d.差额}）</h3>
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

      <h3>本单审计</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>类别</th><th>动作</th><th>备注</th></tr></thead>
          <tbody>
            {audits.map((a) => (
              <tr key={a.编号}><td>{a.时间}</td><td>{a.类别}</td><td>{a.动作}</td><td>{a.备注}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
