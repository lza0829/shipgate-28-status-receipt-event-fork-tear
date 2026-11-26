import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function Events() {
  const [rows, setRows] = useState([])
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
      setRows(await api(`/晋升事件${qs ? `?${qs}` : ''}`))
    } catch (e) { setErr(e.message) }
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  return (
    <div className="panel">
      <h2>事件列表 · 晋升事件流</h2>
      <p className="muted">每单发版单内事件序号单调连续；纠偏作废的越位事件默认置灰保留留痕。</p>
      {err && <p className="err">{err}</p>}
      <div className="row">
        <label>按发版单编号筛选<input value={rid} onChange={(e) => setRid(e.target.value)} placeholder="如 1" /></label>
        <label className="check"><input type="checkbox" checked={includeVoid} onChange={(e) => setIncludeVoid(e.target.checked)} /> 含作废/补录留痕</label>
        <button type="button" onClick={load}>查询</button>
        <button type="button" className="secondary" onClick={() => { setRid(''); setIncludeVoid(true) }}>重置</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>序号</th><th>发版单</th><th>单内序号</th><th>时间</th><th>起始环境</th><th>目标环境</th><th>裁决</th><th>来源</th><th>状态</th><th>备注</th></tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.编号} className={e.作废 ? 'row-void' : ''}>
                <td>{e.编号}</td>
                <td><Link to={`/发版单/${e.发版单编号}`}>#{e.发版单编号}</Link></td>
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
