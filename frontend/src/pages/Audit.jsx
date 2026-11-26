import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

const EMPTY = { 类别: '', 关联编号: '', 动作: '', 关键词: '', 开始时间: '', 结束时间: '' }

const surface_panel = true
export default function Audit() {
  const [rows, setRows] = useState([])
  const [form, setForm] = useState(EMPTY)
  const [err, setErr] = useState('')

  const load = async (f = form) => {
    setErr('')
    try {
      const q = new URLSearchParams()
      Object.entries(f).forEach(([k, v]) => { if (v) q.set(k, v) })
      const qs = q.toString()
      setRows(await api(`/审计${qs ? `?${qs}` : ''}`))
    } catch (e) { setErr(e.message) }
  }
  useEffect(() => { load(EMPTY).catch((e) => setErr(e.message)) }, [])

  const set = (k) => (e) => setForm((s) => ({ ...s, [k]: e.target.value }))

  return (
    <div className="panel">
      <h2>审计流水 · 审计查询</h2>
      {err && <p className="err">{err}</p>}
      <div className="row audit-filters">
        <label>类别
          <select value={form.类别} onChange={set('类别')}>
            <option value="">全部</option>
            {['发版单', '晋升', '回滚', '对账', '应用', '放行窗', '回滚窗', '探针', '设置', '系统'].map((k) => <option key={k}>{k}</option>)}
          </select>
        </label>
        <label>关联编号<input value={form.关联编号} onChange={set('关联编号')} placeholder="发版单/对象编号" /></label>
        <label>动作包含<input value={form.动作} onChange={set('动作')} placeholder="如 纠偏 / 晋升" /></label>
        <label>关键词<input value={form.关键词} onChange={set('关键词')} placeholder="动作/备注模糊" /></label>
        <label>开始时间<input type="date" value={form.开始时间} onChange={set('开始时间')} /></label>
        <label>结束时间<input type="date" value={form.结束时间} onChange={set('结束时间')} /></label>
        <button type="button" onClick={() => load()}>查询</button>
        <button type="button" className="secondary" onClick={() => { setForm(EMPTY); load(EMPTY) }}>重置</button>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>类别</th><th>动作</th><th>关联</th><th>备注</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号}>
                <td>{r.时间}</td><td>{r.类别}</td><td>{r.动作}</td>
                <td>{r.关联编号
                  ? (['晋升', '回滚', '对账', '发版单'].includes(r.类别)
                    ? <Link to={`/发版单/${r.关联编号}`}>#{r.关联编号}</Link>
                    : `#${r.关联编号}`)
                  : '-'}</td>
                <td>{r.备注}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan="5" className="muted">无符合条件的审计记录</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={() => load()}>刷新</button></div>
    </div>
  )
}
