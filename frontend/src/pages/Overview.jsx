import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function Overview() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const load = () => api('/总览').then(setData).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  if (err) return <div className="panel err">{err}</div>
  if (!data) return <div className="panel">加载中</div>
  const d = data.分布 || {}
  const gaps = data.缺口 || []
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
        <div className={`stat ${(data.缺口数 || 0) ? 'stat-bad' : ''}`}>
          <div className="n">{data.缺口数 ?? 0}</div><div className="l">缺口未清</div>
        </div>
        {Object.entries(d).map(([k, v]) => (
          <div className={`stat ${k === '放行缺口' && v ? 'stat-bad' : ''}`} key={k}>
            <div className="n">{v}</div><div className="l">{k}</div>
          </div>
        ))}
      </div>

      <h2>总览环境分布格（按发版单当前环境）</h2>
      <div className="grid">
        {(data.环境分布 || []).map((e) => (
          <div className={`stat ${(e.缺口数 || 0) ? 'stat-bad' : ''}`} key={e.环境}>
            <div className="n">{e.单据数}</div>
            <div className="l">
              {e.环境} · {e.环境名}（在途 {e.在途数} / 已放行 {e.已放行数}）
              {(e.缺口数 || 0) > 0 && <span className="badge bad">缺口 {e.缺口数}</span>}
              {(e.假已放行数 || 0) > 0 && <span className="badge bad">假已放行 {e.假已放行数}</span>}
            </div>
          </div>
        ))}
      </div>

      {gaps.length > 0 && (
        <>
          <h2>缺口未清（钉住，不得当已对齐）</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>发版单号</th><th>应用</th><th>真源状态</th><th>真源环境</th><th>重放环境</th><th>环境链</th><th>缺口类型</th></tr></thead>
              <tbody>
                {gaps.map((g) => (
                  <tr key={g.编号} className="row-bad">
                    <td><Link to={`/发版单/${g.编号}`}>{g.发版单号}</Link></td>
                    <td>{g.应用 || '-'}</td>
                    <td>{g.真源状态}{g.假已放行 && <> <span className="badge bad">假已放行</span></>}</td>
                    <td>{g.真源环境 || '-'}</td>
                    <td>{g.重放环境 || '-'}</td>
                    <td className="muted">{(g.环境链 || []).join(' → ') || '-'}</td>
                    <td>{(g.缺口类型 || []).map((t) => <span key={t} className="badge warn">{t}</span>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h2>在途发版</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>发版单号</th><th>应用</th><th>目标版本</th><th>状态</th><th>当前环境</th><th>重放环境</th><th>流水线</th></tr></thead>
          <tbody>
            {(data.在途 || []).map((r) => (
              <tr key={r.编号} className={r.缺口未清 ? 'row-bad' : ''}>
                <td><Link to={`/发版单/${r.编号}`}>{r.发版单号}</Link></td>
                <td>{r.应用}</td><td>{r.目标版本}</td>
                <td>
                  <span className={`badge st-${r.状态}`}>{r.状态}</span>{' '}
                  {r.假已放行 && <span className="badge bad">假已放行</span>}
                </td>
                <td>{r.当前环境 || '-'}</td>
                <td>{r.重放环境 || '-'}</td>
                <td>{r.流水线}</td>
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
