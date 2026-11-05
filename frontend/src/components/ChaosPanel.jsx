import { useState } from 'react'
import {
  Zap, Wind, Construction, RotateCcw, Truck, Triangle,
  HeartPulse, ChevronDown, ChevronRight, AlertTriangle, Radio
} from 'lucide-react'

const scenarios = [
  {
    id: 'scenario_a',
    icon: Truck,
    color: '#22d3ee',
    title: 'Morning Multi-Depot Peak Load',
    desc: '5 simultaneous orders across 2 regional fulfillment hubs',
    tag: 'SCENARIO A',
  },
  {
    id: 'scenario_b',
    icon: Triangle,
    color: '#a78bfa',
    title: 'Triangular Milk-Run Dispatch',
    desc: 'Depot A → Customer → Depot B chained delivery',
    tag: 'SCENARIO B',
  },
  {
    id: 'scenario_c',
    icon: HeartPulse,
    color: '#f87171',
    title: 'High-Priority Medical Delivery',
    desc: 'Organ/blood transport — priority override active',
    tag: 'SCENARIO C',
  },
]

const chaosButtons = [
  {
    id: 'chaos_pad',
    icon: Zap,
    emoji: '⚡',
    color: '#fbbf24',
    title: 'Inject Depot Pad Congestion',
    desc: 'Blocks Pad 1 at Central Depot',
    chaosKey: 'pad_congestion',
  },
  {
    id: 'chaos_wind',
    icon: Wind,
    emoji: '🌪️',
    color: '#fb923c',
    title: 'Inject 45 km/h Micro-Burst',
    desc: '+60% battery discharge rate',
    chaosKey: 'microburst',
  },
  {
    id: 'chaos_obstacle',
    icon: Construction,
    emoji: '🚧',
    color: '#f87171',
    title: 'Inject Drop-Zone Obstacle',
    desc: 'Obstructed landing at destination',
    chaosKey: 'drop_zone_obstacle',
  },
]

export default function ChaosPanel({ sendCommand, chaosState }) {
  const [scenariosOpen, setScenariosOpen] = useState(true)
  const [chaosOpen, setChaosOpen] = useState(true)

  return (
    <div className="h-full flex flex-col gap-2 overflow-y-auto pr-1">
      {/* Scenarios Section */}
      <div className="glass-panel p-3">
        <button
          className="flex items-center gap-2 w-full text-left mb-2"
          onClick={() => setScenariosOpen(!scenariosOpen)}
        >
          {scenariosOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Radio size={14} style={{ color: '#22d3ee' }} />
          <span className="text-[10px] font-bold tracking-widest" style={{ color: '#94a3b8' }}>
            ENTERPRISE PRESETS
          </span>
        </button>

        {scenariosOpen && (
          <div className="flex flex-col gap-1.5">
            {scenarios.map((s) => {
              const Icon = s.icon
              return (
                <button
                  key={s.id}
                  id={`btn-${s.id}`}
                  className="glow-btn text-left"
                  onClick={() => sendCommand(s.id)}
                >
                  <div className="flex items-start gap-2">
                    <Icon size={14} style={{ color: s.color, marginTop: 2, flexShrink: 0 }} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5 mb-0.5">
                        <span
                          className="text-[8px] font-bold px-1.5 py-0.5 rounded"
                          style={{
                            background: `${s.color}15`,
                            color: s.color,
                            border: `1px solid ${s.color}30`,
                          }}
                        >
                          {s.tag}
                        </span>
                      </div>
                      <div className="text-[11px] font-semibold" style={{ color: '#e2e8f0' }}>
                        {s.title}
                      </div>
                      <div className="text-[9px]" style={{ color: '#64748b' }}>
                        {s.desc}
                      </div>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Chaos Engine Section */}
      <div className="glass-panel p-3">
        <button
          className="flex items-center gap-2 w-full text-left mb-2"
          onClick={() => setChaosOpen(!chaosOpen)}
        >
          {chaosOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <AlertTriangle size={14} style={{ color: '#fbbf24' }} />
          <span className="text-[10px] font-bold tracking-widest" style={{ color: '#94a3b8' }}>
            CHAOS ENGINE
          </span>
        </button>

        {chaosOpen && (
          <div className="flex flex-col gap-1.5">
            <p className="text-[9px] mb-1" style={{ color: '#64748b' }}>
              Inject mid-flight disruptions during active scenarios
            </p>
            {chaosButtons.map((c) => {
              const isActive = chaosState?.[c.chaosKey]
              return (
                <button
                  key={c.id}
                  id={`btn-${c.id}`}
                  className={`glow-btn chaos ${isActive ? 'ring-1' : ''}`}
                  onClick={() => sendCommand(c.id)}
                  style={isActive ? {
                    borderColor: c.color,
                    background: `${c.color}10`,
                    boxShadow: `0 0 12px ${c.color}20`,
                  } : {}}
                >
                  <div className="flex items-start gap-2">
                    <span className="text-sm shrink-0" style={{ marginTop: 1 }}>{c.emoji}</span>
                    <div className="min-w-0">
                      <div className="text-[11px] font-semibold" style={{ color: '#e2e8f0' }}>
                        {c.title}
                      </div>
                      <div className="text-[9px]" style={{ color: '#64748b' }}>
                        {c.desc}
                      </div>
                      {isActive && (
                        <span
                          className="inline-block mt-1 text-[8px] font-bold px-1.5 py-0.5 rounded"
                          style={{
                            background: `${c.color}20`,
                            color: c.color,
                            border: `1px solid ${c.color}40`,
                          }}
                        >
                          ACTIVE
                        </span>
                      )}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Reset */}
      <button
        id="btn-reset"
        className="glow-btn danger flex items-center justify-center gap-2 py-2.5"
        onClick={() => sendCommand('reset')}
      >
        <RotateCcw size={13} />
        <span className="text-[11px]">Reset Simulation</span>
      </button>

      {/* System Info */}
      <div className="glass-panel p-3 mt-auto">
        <div className="text-[9px] font-bold tracking-widest mb-2" style={{ color: '#64748b' }}>
          SYSTEM INFO
        </div>
        <div className="space-y-1">
          {[
            ['Engine', 'Deterministic Sim v1.0'],
            ['Agents', '4 (Dispatcher, Corridor, TAT, Resolver)'],
            ['Weather', 'Open-Meteo API (Live)'],
            ['Routing', 'A* + NetworkX'],
            ['Tick Rate', '500ms'],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between">
              <span className="text-[9px]" style={{ color: '#64748b' }}>{k}</span>
              <span className="text-[9px] font-medium" style={{ color: '#94a3b8' }}>{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
