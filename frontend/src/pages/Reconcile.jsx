import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

const surface_panel = true
export default function Reconcile() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => api('/对账').then(setData).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  const repair = async (rid) => {
    setErr(''); setMsg(''); setBusy(true)
    try {
      const path = rid ? `/发版单/${rid}/纠偏` : '/对账/纠偏'
      const out = await api(path, { method: 'POST', body: '{}' })
      const n = Array.isArray(out.修复) ? out.修复.length : (out.修复?.修复项?.length ? 1 : 0)
      setMsg(rid ? `单据 #${rid} 纠偏完成` : `一键纠偏完成，处理 ${n} 张异常单`)
      await load()
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (err && !data) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const s = data.发版统计 || {}

  return (
    <div className="panel">
      <div className="detail-head">
        <h2>发布对账 · 按发版单状态机真源核验</h2>
        <button type="button" disabled={busy} onClick={() => repair()}>一键纠偏所有差异</button>
      </div>
      {err && <p className="err">{err}</p>}
      {msg && <p className="ok-msg">{msg}</p>}

      <div className="grid">
        <div className={`stat ${data.差额 ? 'stat-bad' : 'stat-ok'}`}>
          <div className="n">{data.差额}</div><div className="l">对账差额</div>
        </div>
        <div className={`stat ${data.一致 ? 'stat-ok' : 'stat-bad'}`}>
          <div className="n">{data.对账结果}</div><div className="l">真源/事件/名册</div>
        </div>
        {Object.entries(s).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
        <div className="stat"><div className="n">{data.晋升事件数}</div><div className="l">晋升事件数</div></div>
      </div>

      <h3>发版单对账重放</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>发版单号</th><th>真源状态</th><th>真源环境</th><th>事件重放环境</th><th>环境链</th>
              <th>序号</th><th>差额</th><th>差异说明</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {(data.对账明细 || []).map((r) => (
              <tr key={r.编号} className={r.一致 ? '' : 'row-bad'}>
                <td><Link to={`/发版单/${r.编号}`}>{r.发版单号}</Link></td>
                <td>{r.真源状态}</td>
                <td>{r.真源环境 || '-'}</td>
                <td>{r.重放环境 || '-'}</td>
                <td className="muted">{(r.环境链 || []).join(' → ') || '-'}</td>
                <td>{(r.事件序号 || []).join(',') || '-'}</td>
                <td>{r.差额 ? <span className="badge bad">{r.差额}</span> : <span className="badge ok">0</span>}</td>
                <td>
                  {(r.差异 || []).map((x, i) => (
                    <div key={i}><span className="badge warn">{x.类型}</span> <span className="muted">{x.说明}</span></div>
                  ))}
                  {r.一致 && <span className="muted">一致</span>}
                </td>
                <td>
                  {r.差额 > 0 && (
                    <button type="button" disabled={busy} onClick={() => repair(r.编号)}>纠偏</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>名册与实例（名册版本列）</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>名册版本</th><th>实例版本们</th><th>红灯数</th><th>版本一致</th></tr></thead>
          <tbody>
            {(data.名册与实例 || []).map((r, i) => (
              <tr key={i} className={r.版本一致 ? '' : 'row-warn'}>
                <td>{r.应用}</td><td>{r.环境}</td>
                <td className="roster-ver">{r.名册版本 || '-'}</td>
                <td>{r.实例版本们 || '-'}</td>
                <td>{r.红灯数}</td>
                <td>{r.版本一致 ? <span className="badge ok">一致</span> : <span className="badge warn">请核查</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={() => load().catch((e) => setErr(e.message))}>刷新</button></div>
    </div>
  )
}
