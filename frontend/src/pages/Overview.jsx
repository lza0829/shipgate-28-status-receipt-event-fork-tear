import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

const surface_panel = true
export default function Overview() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/总览').then(setData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const d = data.分布 || {}
  return (
    <div className="panel">
      <div className="detail-head">
        <h2>总览</h2>
        <Link to="/对账">前往对账 →</Link>
      </div>

      <div className="grid">
        <div className={`stat ${data.真源一致 ? 'stat-ok' : 'stat-bad'}`}>
          <div className="n">{data.真源一致 ? '一致' : `差额 ${data.对账差额}`}</div>
          <div className="l">晋升真源核对</div>
        </div>
        <div className="stat"><div className="n">{data.异常单数 ?? '-'}</div><div className="l">异常单数</div></div>
        {Object.entries(d).map(([k, v]) => (
          <div className="stat" key={k}><div className="n">{v}</div><div className="l">{k}</div></div>
        ))}
      </div>

      <h2>总览环境分布格（按发版单当前环境）</h2>
      <div className="grid">
        {(data.环境分布 || []).map((e) => (
          <div className="stat" key={e.环境}>
            <div className="n">{e.单据数}</div>
            <div className="l">{e.环境} · {e.环境名}（在途 {e.在途数} / 已放行 {e.已放行数}）</div>
          </div>
        ))}
      </div>

      <h2>在途发版</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th><th>流水线</th></tr></thead>
          <tbody>
            {(data.在途 || []).map((r) => (
              <tr key={r.编号}>
                <td><Link to={`/发版单/${r.编号}`}>{r.发版单号}</Link></td>
                <td>{r.应用}</td><td>{r.目标版本}</td>
                <td><span className={`badge st-${r.状态}`}>{r.状态}</span></td>
                <td>{r.当前环境 || '-'}</td><td>{r.流水线}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>各环境版本</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>应用</th><th>环境</th><th>版本</th><th>更新时间</th></tr></thead>
          <tbody>
            {(data.环境版本 || []).map((v, i) => (
              <tr key={i}><td>{v.应用}</td><td>{v.环境}</td><td>{v.版本}</td><td>{v.更新时间}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row"><button type="button" className="secondary" onClick={load}>刷新</button></div>
    </div>
  )
}
