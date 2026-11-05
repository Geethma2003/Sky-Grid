import { useEffect, useRef } from 'react'
import { Terminal, Pause, Play, Trash2 } from 'lucide-react'

// Agent color mapping
const AGENT_COLORS = {
  DISPATCHER: { color: '#22d3ee', bg: '#22d3ee15', label: 'DISPATCHER' },
  CORRIDOR:   { color: '#34d399', bg: '#34d39915', label: 'CORRIDOR' },
  'TAT-DEPOT':{ color: '#a78bfa', bg: '#a78bfa15', label: 'TAT-DEPOT' },
  RESOLVER:   { color: '#fbbf24', bg: '#fbbf2415', label: 'RESOLVER' },
}

function formatTimestamp(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('en-US', {
    hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function LogEntry({ log }) {
  const agentStyle = AGENT_COLORS[log.agent] || { color: '#94a3b8', bg: '#94a3b815', label: log.agent }

  return (
    <div className="log-entry px-3 py-2 border-b" style={{ borderColor: '#1e293b10' }}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[8px] font-mono" style={{ color: '#475569' }}>
          {formatTimestamp(log.timestamp)}
        </span>
        <span
          className="text-[8px] font-bold px-1.5 py-0.5 rounded"
          style={{
            color: agentStyle.color,
            background: agentStyle.bg,
            border: `1px solid ${agentStyle.color}25`,
          }}
        >
          [{agentStyle.label}]
        </span>
      </div>
      <div
        className="text-[11px] leading-relaxed"
        style={{
          color: '#cbd5e1',
          fontFamily: "'JetBrains Mono', monospace",
          wordBreak: 'break-word',
        }}
      >
        {log.message}
      </div>
    </div>
  )
}

export default function AgentConsole({ logs }) {
  const scrollRef = useRef(null)
  const autoScrollRef = useRef(true)

  useEffect(() => {
    if (autoScrollRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs])

  const handleScroll = () => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    autoScrollRef.current = scrollHeight - scrollTop - clientHeight < 50
  }

  return (
    <div className="glass-panel h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: '#1e293b' }}>
        <div className="flex items-center gap-2">
          <Terminal size={14} style={{ color: '#22d3ee' }} />
          <span className="text-[10px] font-bold tracking-widest" style={{ color: '#94a3b8' }}>
            MULTI-AGENT OPERATIONS TERMINAL
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[9px] tabular-nums" style={{ color: '#475569' }}>
            {logs.length} entries
          </span>
          <div className="w-2 h-2 rounded-full bg-emerald-400 ml-1"
            style={{ animation: logs.length > 0 ? 'pulse-ring 2s infinite' : 'none' }}
          />
        </div>
      </div>

      {/* Agent Legend */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-b" style={{ borderColor: '#1e293b08' }}>
        {Object.entries(AGENT_COLORS).map(([key, val]) => (
          <div key={key} className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full" style={{ background: val.color }} />
            <span className="text-[8px] font-semibold" style={{ color: val.color }}>
              {val.label}
            </span>
          </div>
        ))}
      </div>

      {/* Log Stream */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
        style={{ background: 'rgba(10, 14, 26, 0.4)' }}
      >
        {logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2">
            <Terminal size={24} style={{ color: '#1e293b' }} />
            <p className="text-[11px]" style={{ color: '#334155' }}>
              Awaiting agent activity...
            </p>
            <p className="text-[9px]" style={{ color: '#1e293b' }}>
              Launch a scenario from the left panel
            </p>
          </div>
        ) : (
          logs.map((log, i) => <LogEntry key={log.id || i} log={log} />)
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-3 py-1.5 border-t" style={{ borderColor: '#1e293b' }}>
        <span className="text-[8px] font-mono" style={{ color: '#334155' }}>
          ws://localhost:8000/ws
        </span>
        <span className="text-[8px]" style={{ color: '#334155' }}>
          SkyGrid Enterprise v1.0
        </span>
      </div>
    </div>
  )
}
