import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function Promote() {
  const [rows, setRows] = useState([])
  const [rid, setRid] = useState('')
  const [env, setEnv] = useState('预')
  const [detail, setDetail] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = async (keepRid) => {
    const all = await api('/发版单')
    const active = all.filter((r) => ['已入闸', '晋升中'].includes(r.状态))
    setRows(active)
    const currentRid = keepRid || rid || (active[0] && String(active[0].编号)) || ''
    if (!rid && currentRid) setRid(currentRid)
    if (currentRid) {
      try { setDetail(await api(`/发版单/${currentRid}`)) } catch { setDetail(null) }
    }
  }
  useEffect(() => { load().catch((e) => setErr(e.message)) }, [])

  const changeRid = async (v) => {
    setRid(v); setErr(''); setMsg('')
    try { setDetail(await api(`/发版单/${v}`)) } catch (e) { setErr(e.message) }
  }

  const go = async () => {
    setErr(''); setMsg('')
    try {
      const out = await api(`/发版单/${rid}/晋升`, { method: 'POST', body: JSON.stringify({ 目标环境: env }) })
      setMsg(`晋升成功：${out.状态} / ${out.当前环境}，事件序号 ${(out.事件 || []).map((e) => e.序号).join(',')}`)
      await load(rid)
    } catch (e) { setErr(e.message) }
  }

  return (
    <div className="panel">
      <h2>环境晋升 · 晋升入口</h2>
      <p className="muted">状态推进与事件写入同笔事务；并发晋升由状态版本 + 写锁保证只成一单。</p>
      {err && <p className="err">{err}</p>}
      {msg && <p className="ok-msg">{msg}</p>}
      <div className="row">
        <label>发版单
          <select value={rid} onChange={(e) => changeRid(e.target.value)}>
            {rows.map((r) => <option key={r.编号} value={r.编号}>{r.发版单号} · {r.应用} · 当前 {r.当前环境}</option>)}
          </select>
        </label>
        <label>目标环境
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="测">测</option>
            <option value="预">预</option>
            <option value="产">产</option>
          </select>
        </label>
        <button type="button" onClick={go}>晋升</button>
        <button type="button" className="secondary" onClick={() => load(rid).catch((e) => setErr(e.message))}>刷新</button>
        {rid && <Link className="btn-link" to={`/发版单/${rid}`}>查看发版单详情 →</Link>}
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th><th>重放环境</th><th>核对</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.编号} className={r.一致 === false ? 'row-bad' : ''}>
                <td><Link to={`/发版单/${r.编号}`}>{r.发版单号}</Link></td>
                <td>{r.应用}</td><td>{r.目标版本}</td><td>{r.状态}</td><td>{r.当前环境}</td>
                <td>{r.重放环境 || '-'}</td>
                <td>{r.一致 === false ? <span className="badge bad">差额 {r.差额}</span> : <span className="badge ok">一致</span>}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan="7" className="muted">当前没有可晋升的发版单</td></tr>}
          </tbody>
        </table>
      </div>

      {detail && (
        <>
          <h3>#{detail.编号} 事件序号链</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>序号</th><th>时间</th><th>起始</th><th>目标</th><th>来源</th><th>备注</th></tr></thead>
              <tbody>
                {(detail.事件 || []).map((e) => (
                  <tr key={e.编号}><td>{e.序号}</td><td>{e.时间}</td><td>{e.起始环境 || '-'}</td><td>{e.目标环境}</td><td>{e.来源}</td><td>{e.备注}</td></tr>
                ))}
                {(detail.事件 || []).length === 0 && <tr><td colSpan="6" className="muted">暂无晋升事件</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
