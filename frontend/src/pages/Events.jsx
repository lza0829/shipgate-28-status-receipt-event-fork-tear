import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function Events() {
  const [rows, setRows] = useState([])
  const [cross, setCross] = useState(null)
  const [rid, setRid] = useState('')
  const [includeVoid, setIncludeVoid] = useState(true)
  const [err, setErr] = useState('')

  const load = async () => {
    setErr('')
    try {
      const q = new URLSearchParams()
      if (rid) q.set('发版单编号', rid)
      if (includeVoid) q.set('含作废', 'true')
      const qs = q.toString()
      const [eventRows, crossRead] = await Promise.all([
        api(`/晋升事件${qs ? `?${qs}` : ''}`),
        api('/晋升事件/对照'),
      ])
      setRows(eventRows)
      setCross(crossRead)
    } catch (e) { setErr(e.message) }
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  const torn = new Set((cross?.对照 || []).filter((c) => c.缺口未清).map((c) => c.编号))
  const crossRows = (cross?.对照 || []).filter((c) => !rid || String(c.编号) === String(rid))

  return (
    <div className="panel">
      <h2>事件列表 · 晋升事件流</h2>
      <p className="muted">每单发版单内事件序号单调连续；纠偏作废的越位事件默认置灰保留留痕。事件环境链与单态/名册同屏对照，撕裂单钉缺口。</p>
      {err && <p className="err">{err}</p>}
      <div className="row">
        <label>按发版单编号筛选<input value={rid} onChange={(e) => setRid(e.target.value)} placeholder="如 1" /></label>
        <label className="check"><input type="checkbox" checked={includeVoid} onChange={(e) => setIncludeVoid(e.target.checked)} /> 含作废/补录留痕</label>
        <button type="button" onClick={load}>查询</button>
        <button type="button" className="secondary" onClick={() => { setRid(''); setIncludeVoid(true) }}>重置</button>
      </div>

      <h3>晋升事件流环境链 × 单态 × 名册 对照</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>发版单</th><th>状态</th><th>真源环境</th><th>重放环境</th><th>环境链</th><th>序号</th><th>名册@真源</th><th>已放行灯</th><th>缺口</th></tr>
          </thead>
          <tbody>
            {crossRows.map((c) => (
              <tr key={c.编号} className={c.缺口未清 ? 'row-bad' : ''}>
                <td><Link to={`/发版单/${c.编号}`}>{c.发版单号}</Link></td>
                <td>{c.状态}</td>
                <td>{c.真源环境 || '-'}</td>
                <td>{c.重放环境 || '-'}</td>
                <td className="muted">{(c.环境链 || []).join(' → ') || '-'}</td>
                <td>{(c.事件序号 || []).join(',') || '-'}{c.序号连续 ? '' : '（断号）'}</td>
                <td>{c.名册版本 || '-'}<span className="muted"> / {c.目标版本 || '-'}</span></td>
                <td>
                  {c.已放行灯
                    ? (c.放行成立 ? <span className="badge ok">成立</span> : <span className="badge bad">假已放行</span>)
                    : <span className="muted">未亮</span>}
                </td>
                <td>{c.缺口未清 ? (c.缺口类型 || []).map((t) => <span key={t} className="badge warn">{t}</span>) : <span className="badge ok">无</span>}</td>
              </tr>
            ))}
            {crossRows.length === 0 && <tr><td colSpan="9" className="muted">暂无发版单</td></tr>}
          </tbody>
        </table>
      </div>

      <h3>事件流水</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>序号</th><th>发版单</th><th>单内序号</th><th>时间</th><th>起始环境</th><th>目标环境</th><th>裁决</th><th>来源</th><th>状态</th><th>备注</th></tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.编号} className={`${e.作废 ? 'row-void' : ''} ${torn.has(e.发版单编号) ? 'row-bad' : ''}`}>
                <td>{e.编号}</td>
                <td><Link to={`/发版单/${e.发版单编号}`}>#{e.发版单编号}</Link>{torn.has(e.发版单编号) && <> <span className="badge bad">缺口</span></>}</td>
                <td>{e.序号 ?? '-'}</td>
                <td>{e.时间}</td>
                <td>{e.起始环境 || '-'}</td>
                <td>{e.目标环境}</td>
                <td>{e.裁决}</td>
                <td>{e.来源}</td>
                <td>{e.作废 ? <span className="badge bad">已作废</span> : <span className="badge ok">有效</span>}</td>
                <td>{e.备注}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan="10" className="muted">暂无晋升事件</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
