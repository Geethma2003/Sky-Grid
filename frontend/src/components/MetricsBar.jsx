import {
  Plane, Battery, TrendingDown, LayoutGrid, DollarSign,
  Package, Activity, Wifi, WifiOff
} from 'lucide-react'

const metricDefs = [
  {
    key: 'active_drones',
    label: 'Active Drones',
    icon: Plane,
    color: '#22d3ee',
    format: v => v || 0,
    suffix: '',
  },
  {
    key: 'fleet_soh_avg',
    label: 'Fleet SoH Avg',
    icon: Battery,
    color: '#34d399',
    format: v => (v || 0).toFixed(1),
    suffix: '%',
  },
  {
    key: 'avg_battery',
    label: 'Avg Battery',
    icon: Activity,
    color: '#60a5fa',
    format: v => (v || 0).toFixed(1),
    suffix: '%',
  },
  {
    key: 'deadhead_reduced_pct',
    label: 'Deadhead Reduced',
    icon: TrendingDown,
    color: '#a78bfa',
    format: v => (v || 0).toFixed(1),
    suffix: '%',
  },
  {
    key: 'pad_utilization_pct',
    label: 'Pad Utilization',
    icon: LayoutGrid,
    color: '#fbbf24',
    format: v => (v || 0).toFixed(1),
    suffix: '%',
  },
  {
    key: 'total_deliveries',
    label: 'Deliveries',
    icon: Package,
    color: '#f472b6',
    format: v => v || 0,
    suffix: '',
  },
  {
    key: 'cost_savings_usd',
    label: 'Cost Savings',
    icon: DollarSign,
    color: '#34d399',
    format: v => (v || 0).toFixed(0),
    suffix: '',
    prefix: '$',
  },
]

export default function MetricsBar({ metrics, connected }) {
  return (
    <div className="flex items-center gap-2 px-3 py-2">
      {/* Brand */}
      <div className="flex items-center gap-2 mr-3 shrink-0">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{
            background: 'linear-gradient(135deg, #22d3ee 0%, #6366f1 100%)',
            boxShadow: '0 0 20px rgba(34, 211, 238, 0.3)',
          }}
        >
          <Plane size={16} className="text-white" style={{ transform: 'rotate(-45deg)' }} />
        </div>
        <div>
          <h1 className="text-sm font-bold tracking-wide"
            style={{
              background: 'linear-gradient(90deg, #22d3ee, #a78bfa)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            SKYGRID ENTERPRISE
          </h1>
          <p className="text-[9px] font-medium tracking-widest" style={{ color: '#64748b' }}>
            MISSION OPERATIONS CENTER
          </p>
        </div>
      </div>

      {/* Divider */}
      <div className="w-px h-8 shrink-0" style={{ background: '#1e293b' }} />

      {/* Metrics */}
      <div className="flex-1 flex items-center gap-1.5 overflow-x-auto">
        {metricDefs.map((m) => {
          const Icon = m.icon
          const val = metrics ? m.format(metrics[m.key]) : '—'
          return (
            <div
              key={m.key}
              className="metric-card glass-panel flex items-center gap-2 px-3 py-1.5 shrink-0"
              style={{ minWidth: 'fit-content' }}
            >
              <Icon size={14} style={{ color: m.color }} />
              <div>
                <div className="text-[9px] font-medium tracking-wider" style={{ color: '#64748b' }}>
                  {m.label.toUpperCase()}
                </div>
                <div className="text-sm font-bold tabular-nums" style={{ color: m.color }}>
                  {m.prefix || ''}{val}{m.suffix}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Connection Status */}
      <div className="shrink-0 flex items-center gap-1.5 px-3 py-1.5 glass-panel">
        {connected ? (
          <>
            <Wifi size={12} className="text-emerald-400" />
            <span className="text-[10px] font-semibold text-emerald-400">LIVE</span>
          </>
        ) : (
          <>
            <WifiOff size={12} className="text-red-400" />
            <span className="text-[10px] font-semibold text-red-400">OFFLINE</span>
          </>
        )}
      </div>
    </div>
  )
}
