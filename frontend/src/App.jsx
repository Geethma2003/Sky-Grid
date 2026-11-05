import { useState, useEffect, useRef, useCallback } from 'react'
import MissionMap from './components/MissionMap'

const WS_URL = `ws://${window.location.hostname}:8000/ws`
const API_URL = `http://${window.location.hostname}:8000`

const AGENT_COLORS = {
  DISPATCHER: '#38bdf8',
  CORRIDOR:   '#34d399',
  'TAT-DEPOT':'#a78bfa',
  RESOLVER:   '#fb923c',
}

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function App() {
  const [state, setState] = useState(null)
  const [logs, setLogs]   = useState([])
  const [connected, setConnected] = useState(false)
  const [activeTab, setActiveTab]  = useState('scenarios')
  const [modelInfo, setModelInfo] = useState(null)
  const [benchResults, setBenchResults] = useState(null)
  const [benchLoading, setBenchLoading] = useState(false)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const logEndRef = useRef(null)

  /* ── WebSocket ── */
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws
    ws.onopen    = () => setConnected(true)
    ws.onclose   = () => { setConnected(false); reconnectTimer.current = setTimeout(connect, 2000) }
    ws.onerror   = () => ws.close()
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'command_result') {
          if (data.logs?.length) setLogs(p => [...p, ...data.logs].slice(-200))
          return
        }
        setState(data)
        if (data.new_logs?.length) setLogs(p => [...p, ...data.new_logs].slice(-200))
      } catch {}
    }
  }, [])

  useEffect(() => {
    connect()
    return () => { wsRef.current?.close(); clearTimeout(reconnectTimer.current) }
  }, [connect])

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  /* ── Load model info ── */
  useEffect(() => {
    fetch(`${API_URL}/api/model`).then(r => r.json()).then(setModelInfo).catch(() => {})
    fetch(`${API_URL}/api/benchmark/results`).then(r => r.json()).then(setBenchResults).catch(() => {})
  }, [])

  const send = useCallback((cmd) => {
    if (wsRef.current?.readyState === WebSocket.OPEN)
      wsRef.current.send(JSON.stringify({ command: cmd, data: {} }))
  }, [])

  const runBenchmark = useCallback(async () => {
    setBenchLoading(true)
    try {
      const resp = await fetch(`${API_URL}/api/benchmark`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenarios: 5, orders: 5, seed: 42, strategies: ['baseline', 'skygrid', 'ai_assist'] }),
      })
      const data = await resp.json()
      setBenchResults(data)
      // Also refresh stored results
      const r2 = await fetch(`${API_URL}/api/benchmark/results`)
      const stored = await r2.json()
      setBenchResults(stored)
    } catch (e) { console.error(e) }
    setBenchLoading(false)
  }, [])

  const m = state?.metrics || {}

  const panelStyle = { background: '#13171f', border: '1px solid #1e2535', borderRadius: 8, padding: '10px 12px', marginBottom: 8 }
  const labelStyle = { fontSize: 9, color: '#475569', letterSpacing: 2, marginBottom: 4 }
  const valueStyle = { fontSize: 12, fontWeight: 600, color: '#e2e8f0' }
  const subStyle = { fontSize: 10, color: '#94a3b8' }
  const btnBase = { borderRadius: 8, padding: '8px 12px', cursor: 'pointer', transition: 'all .15s', fontSize: 11, fontWeight: 600, border: '1px solid' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f1117', color: '#e2e8f0', fontFamily: 'Inter, sans-serif', overflow: 'hidden' }}>

      {/* ── Top bar ── */}
      <header style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '0 20px', height: 52, borderBottom: '1px solid #1e2535', background: '#0d1117', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 8 }}>
          <div style={{ width: 30, height: 30, borderRadius: 8, background: 'linear-gradient(135deg,#38bdf8,#6366f1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>✈</div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: 1, background: 'linear-gradient(90deg,#38bdf8,#a78bfa)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>SkyGrid Enterprise</div>
            <div style={{ fontSize: 9, color: '#475569', letterSpacing: 2 }}>FLEET ORCHESTRATOR v2.0</div>
          </div>
        </div>

        <div style={{ width: 1, height: 32, background: '#1e2535' }} />

        {/* Metrics */}
        {[
          { label: 'Active Drones', value: m.active_drones ?? '—', color: '#38bdf8' },
          { label: 'Fleet SoH',     value: m.fleet_soh_avg != null ? m.fleet_soh_avg.toFixed(1) + '%' : '—', color: '#34d399' },
          { label: 'Avg Battery',   value: m.avg_battery != null ? m.avg_battery.toFixed(1) + '%' : '—', color: '#60a5fa' },
          { label: 'Deliveries',    value: m.total_deliveries ?? '—', color: '#f472b6' },
          { label: 'Pad Util.',     value: m.pad_utilization_pct != null ? m.pad_utilization_pct.toFixed(0) + '%' : '—', color: '#fbbf24' },
          { label: 'Cost Saved',    value: m.cost_savings_usd != null ? '$' + m.cost_savings_usd.toFixed(0) : '—', color: '#34d399' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 66 }}>
            <span style={{ fontSize: 9, color: '#475569', letterSpacing: 1 }}>{label.toUpperCase()}</span>
            <span style={{ fontSize: 14, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
          </div>
        ))}

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* ML Model badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 600, color: modelInfo?.model_available ? '#34d399' : '#fbbf24', background: modelInfo?.model_available ? '#34d39910' : '#fbbf2410', padding: '3px 8px', borderRadius: 6, border: `1px solid ${modelInfo?.model_available ? '#34d39930' : '#fbbf2430'}` }}>
            {modelInfo?.model_available ? '🧠 ML Active' : '⚙️ Fallback'}
          </div>
          {/* Connection */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, fontWeight: 600, color: connected ? '#34d399' : '#f87171' }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: connected ? '#34d399' : '#f87171', boxShadow: connected ? '0 0 8px #34d399' : 'none' }} />
            {connected ? 'LIVE' : 'OFFLINE'}
          </div>
        </div>
      </header>

      {/* ── Main ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── Sidebar ── */}
        <aside style={{ width: 260, flexShrink: 0, borderRight: '1px solid #1e2535', background: '#0d1117', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

          {/* Tab switcher */}
          <div style={{ display: 'flex', borderBottom: '1px solid #1e2535' }}>
            {[['scenarios', '🚀 Scenarios'], ['logs', '📋 Logs'], ['bench', '📊 Bench'], ['model', '🧠 Model']].map(([id, label]) => (
              <button key={id} onClick={() => setActiveTab(id)} style={{ flex: 1, padding: '10px 0', fontSize: 10, fontWeight: 600, color: activeTab === id ? '#38bdf8' : '#475569', background: 'none', border: 'none', cursor: 'pointer', borderBottom: activeTab === id ? '2px solid #38bdf8' : '2px solid transparent', transition: 'all .15s' }}>
                {label}
              </button>
            ))}
          </div>

          {activeTab === 'scenarios' ? (
            <div style={{ flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>

              {/* Scenarios */}
              <div style={labelStyle}>MISSION SCENARIOS</div>
              {[
                { id: 'scenario_a', label: 'Scenario A', title: 'Morning Peak Load', desc: '5 simultaneous orders, 2 depots', color: '#38bdf8' },
                { id: 'scenario_b', label: 'Scenario B', title: 'Milk-Run Dispatch', desc: 'Depot A → Customer → Depot B', color: '#a78bfa' },
                { id: 'scenario_c', label: 'Scenario C', title: 'Medical Delivery', desc: 'Priority override, 12 min SLA', color: '#f87171' },
              ].map(s => (
                <button key={s.id} id={`btn-${s.id}`} onClick={() => send(s.id)} style={{ ...btnBase, background: '#13171f', borderColor: `${s.color}30`, textAlign: 'left' }}
                  onMouseEnter={e => e.currentTarget.style.borderColor = s.color}
                  onMouseLeave={e => e.currentTarget.style.borderColor = `${s.color}30`}
                >
                  <div style={{ fontSize: 9, color: s.color, fontWeight: 700, letterSpacing: 1, marginBottom: 3 }}>{s.label.toUpperCase()}</div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: '#e2e8f0', marginBottom: 2 }}>{s.title}</div>
                  <div style={{ fontSize: 10, color: '#475569' }}>{s.desc}</div>
                </button>
              ))}

              <div style={{ height: 1, background: '#1e2535', margin: '4px 0' }} />

              {/* Chaos */}
              <div style={labelStyle}>CHAOS ENGINE</div>
              {[
                { id: 'chaos_pad',      key: 'pad_congestion',      label: 'Pad Congestion', desc: 'Block Pad 1 at Central Hub', color: '#fbbf24' },
                { id: 'chaos_wind',     key: 'microburst',          label: 'Micro-Burst Wind', desc: '+60% battery discharge', color: '#fb923c' },
                { id: 'chaos_obstacle', key: 'drop_zone_obstacle',  label: 'Drop-Zone Block', desc: 'Obstruct landing zone', color: '#f87171' },
              ].map(c => {
                const active = state?.chaos_state?.[c.key]
                return (
                  <button key={c.id} id={`btn-${c.id}`} onClick={() => send(c.id)} style={{ ...btnBase, background: active ? `${c.color}12` : '#13171f', borderColor: active ? c.color : c.color + '25', textAlign: 'left' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: '#e2e8f0' }}>{c.label}</span>
                      {active && <span style={{ fontSize: 8, fontWeight: 700, color: c.color, background: `${c.color}20`, padding: '1px 6px', borderRadius: 4 }}>ACTIVE</span>}
                    </div>
                    <div style={{ fontSize: 10, color: '#475569' }}>{c.desc}</div>
                  </button>
                )
              })}

              <div style={{ flex: 1 }} />

              <button id="btn-reset" onClick={() => send('reset')} style={{ ...btnBase, background: '#1a0f0f', borderColor: '#7f1d1d', color: '#fca5a5' }}
                onMouseEnter={e => { e.currentTarget.style.background = '#2a1515'; e.currentTarget.style.borderColor = '#ef4444' }}
                onMouseLeave={e => { e.currentTarget.style.background = '#1a0f0f'; e.currentTarget.style.borderColor = '#7f1d1d' }}
              >
                ↺ Reset Simulation
              </button>
            </div>
          ) : activeTab === 'logs' ? (
            /* ── Log Panel ── */
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '8px 12px', borderBottom: '1px solid #1e2535' }}>
                {Object.entries(AGENT_COLORS).map(([k, c]) => (
                  <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: c }} />
                    <span style={{ fontSize: 9, color: c, fontWeight: 600 }}>{k}</span>
                  </div>
                ))}
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
                {logs.length === 0 ? (
                  <div style={{ color: '#334155', fontSize: 11, textAlign: 'center', marginTop: 40 }}>No logs yet — run a scenario</div>
                ) : logs.map((log, i) => (
                  <div key={log.id || i} style={{ padding: '6px 4px', borderBottom: '1px solid #1e253510' }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 2 }}>
                      <span style={{ fontSize: 9, color: '#334155', fontFamily: 'monospace' }}>{formatTime(log.timestamp)}</span>
                      <span style={{ fontSize: 8, fontWeight: 700, color: AGENT_COLORS[log.agent] || '#94a3b8', background: (AGENT_COLORS[log.agent] || '#94a3b8') + '18', padding: '1px 5px', borderRadius: 3 }}>{log.agent}</span>
                    </div>
                    <div style={{ fontSize: 10, color: '#94a3b8', lineHeight: 1.5, wordBreak: 'break-word' }}>{log.message}</div>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
              <div style={{ padding: '6px 12px', borderTop: '1px solid #1e2535', fontSize: 9, color: '#334155' }}>{logs.length} entries</div>
            </div>
          ) : activeTab === 'bench' ? (
            /* ── Benchmark Panel ── */
            <div style={{ flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={labelStyle}>BENCHMARK EXPERIMENTS</div>
              <button onClick={runBenchmark} disabled={benchLoading} style={{ ...btnBase, background: '#13171f', borderColor: '#38bdf830', color: '#38bdf8', opacity: benchLoading ? 0.5 : 1 }}>
                {benchLoading ? '⏳ Running...' : '▶ Run Comparison (3 strategies × 5 scenarios)'}
              </button>

              {benchResults?.summary?.length > 0 && (
                <>
                  <div style={labelStyle}>STRATEGY COMPARISON</div>
                  {benchResults.summary.map((row, i) => {
                    const colors = { baseline: '#94a3b8', skygrid: '#38bdf8', ai_assist: '#34d399' }
                    const c = colors[row.strategy] || '#94a3b8'
                    return (
                      <div key={i} style={{ ...panelStyle, borderColor: `${c}40` }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: c, marginBottom: 6, textTransform: 'uppercase' }}>{row.strategy.replace('_', ' ')}</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                          {[
                            ['Delivery Rate', (parseFloat(row.mean_delivery_rate) * 100).toFixed(0) + '%'],
                            ['Energy/Delivery', parseFloat(row.mean_energy_per_delivery).toFixed(1) + '%'],
                            ['Mean Time', parseFloat(row.mean_completion_time_s).toFixed(0) + 's'],
                            ['Latency', parseFloat(row.mean_decision_latency_ms).toFixed(1) + 'ms'],
                            ['Diversions', parseFloat(row.mean_diversions).toFixed(1)],
                            ['Sep. Violations', parseFloat(row.mean_sep_violations).toFixed(1)],
                          ].map(([k, v]) => (
                            <div key={k}>
                              <div style={{ fontSize: 9, color: '#475569' }}>{k}</div>
                              <div style={{ fontSize: 12, fontWeight: 600, color: '#e2e8f0' }}>{v}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </>
              )}

              {!benchResults?.summary?.length && !benchLoading && (
                <div style={{ color: '#334155', fontSize: 11, textAlign: 'center', marginTop: 20 }}>No benchmark results yet. Click Run to start.</div>
              )}
            </div>
          ) : (
            /* ── Model Info Panel ── */
            <div style={{ flex: 1, overflowY: 'auto', padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={labelStyle}>ML MODEL STATUS</div>

              <div style={panelStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: modelInfo?.model_available ? '#34d399' : '#fbbf24' }} />
                  <span style={{ ...valueStyle, color: modelInfo?.model_available ? '#34d399' : '#fbbf24' }}>
                    {modelInfo?.model_available ? 'Model Loaded' : 'Deterministic Fallback'}
                  </span>
                </div>

                {modelInfo && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {[
                      ['Model', modelInfo.selected_model || modelInfo.model_name],
                      ['Dataset Size', modelInfo.dataset_size || '—'],
                      ['Reserve', (modelInfo.battery_reserve_pct || 20) + '%'],
                    ].map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={subStyle}>{k}</span>
                        <span style={{ ...subStyle, color: '#e2e8f0', fontWeight: 600 }}>{v}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {modelInfo?.metrics && Object.keys(modelInfo.metrics).length > 0 && (
                <div style={panelStyle}>
                  <div style={{ ...labelStyle, marginBottom: 6 }}>HELD-OUT TEST METRICS</div>
                  {[
                    ['Time MAE', modelInfo.metrics.test_completion_time_s_mae, 's'],
                    ['Time RMSE', modelInfo.metrics.test_completion_time_s_rmse, 's'],
                    ['Time R²', modelInfo.metrics.test_completion_time_s_r2, ''],
                    ['Energy MAE', modelInfo.metrics.test_energy_consumed_pct_mae, '%'],
                    ['Energy R²', modelInfo.metrics.test_energy_consumed_pct_r2, ''],
                  ].filter(([, v]) => v != null).map(([k, v, u]) => (
                    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                      <span style={subStyle}>{k}</span>
                      <span style={{ ...subStyle, color: '#38bdf8', fontWeight: 600 }}>{typeof v === 'number' ? v.toFixed(4) : v}{u}</span>
                    </div>
                  ))}
                </div>
              )}

              <div style={panelStyle}>
                <div style={{ ...labelStyle, marginBottom: 6 }}>FEATURES ({modelInfo?.feature_names?.length || 0})</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {(modelInfo?.feature_names || []).map(f => (
                    <span key={f} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: '#1e2535', color: '#94a3b8' }}>{f}</span>
                  ))}
                </div>
              </div>

              <div style={{ ...panelStyle, borderColor: '#fbbf2430' }}>
                <div style={{ fontSize: 10, color: '#fbbf24', lineHeight: 1.6 }}>
                  ⚠️ Trained on simulator-generated data. Real-world accuracy unvalidated. Hard safety constraints enforced by dispatcher, not overridden by ML.
                </div>
              </div>
            </div>
          )}
        </aside>

        {/* ── Map ── */}
        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          <MissionMap
            drones={state?.drones}
            depots={state?.depots}
            orders={state?.orders}
            weatherCells={state?.weather_cells}
          />

          {/* Fleet status overlay */}
          {state?.drones && (
            <div style={{ position: 'absolute', top: 12, right: 12, background: 'rgba(13,17,23,0.9)', backdropFilter: 'blur(8px)', border: '1px solid #1e2535', borderRadius: 10, padding: '10px 14px', maxWidth: 220, zIndex: 1000 }}>
              <div style={{ fontSize: 9, color: '#475569', letterSpacing: 2, marginBottom: 6 }}>FLEET STATUS</div>
              {Object.values(state.drones).map(d => {
                const batColor = d.battery_charge > 50 ? '#34d399' : d.battery_charge > 25 ? '#fbbf24' : '#f87171'
                const statusColor = d.status === 'idle' ? '#475569' : d.status.includes('route') || d.status === 'delivering' ? '#38bdf8' : d.status === 'emergency' || d.status === 'rerouting' ? '#f87171' : '#a78bfa'
                return (
                  <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <div style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor, flexShrink: 0 }} />
                    <span style={{ fontSize: 10, color: '#e2e8f0', fontWeight: 600, minWidth: 58 }}>{d.name}</span>
                    <div style={{ flex: 1, height: 4, borderRadius: 2, background: '#1e2535', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${d.battery_charge}%`, background: batColor, borderRadius: 2 }} />
                    </div>
                    <span style={{ fontSize: 9, color: batColor, fontWeight: 600, minWidth: 28, textAlign: 'right' }}>{Math.round(d.battery_charge)}%</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
