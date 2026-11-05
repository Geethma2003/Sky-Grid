import { useMemo } from 'react'
import { MapContainer, TileLayer, Marker, Polyline, Circle, Popup, Tooltip } from 'react-leaflet'
import L from 'leaflet'

const CENTER = [6.9271, 79.8612]
const ZOOM = 13

// ── Drone icon ──────────────────────────────────────────────────────────
function createDroneIcon(drone) {
  let border = '#38bdf8', bg = 'rgba(56,189,248,0.15)'

  if (['returning','landing','battery_swap'].includes(drone.status)) {
    border = '#60a5fa'; bg = 'rgba(96,165,250,0.15)'
  } else if (['rerouting','diverted','emergency'].includes(drone.status)) {
    border = '#f87171'; bg = 'rgba(248,113,113,0.2)'
  }
  if (drone.current_order?.startsWith('MED')) {
    border = '#f87171'; bg = 'rgba(248,113,113,0.2)'
  }

  const batColor = drone.battery_charge > 50 ? '#34d399' : drone.battery_charge > 25 ? '#fbbf24' : '#f87171'
  const rot = (drone.heading_deg || 0) - 90

  return L.divIcon({
    className: '',
    iconSize: [40, 40],
    iconAnchor: [20, 20],
    html: `
      <div style="
        width:40px;height:40px;border-radius:50%;
        border:2px solid ${border};background:${bg};
        display:flex;align-items:center;justify-content:center;
        position:relative;
      ">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
          stroke="${border}" stroke-width="2.5"
          style="transform:rotate(${rot}deg)">
          <path d="M17.8 19.2L16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.4-.1.9.3 1.1L11 12l-2 3H6l-1 1 3 2 2 3 1-1v-3l3-2 4.2 7.3c.2.4.7.5 1.1.3l.5-.3c.4-.2.6-.7.5-1.1z"/>
        </svg>
        <div style="
          position:absolute;bottom:-12px;left:50%;transform:translateX(-50%);
          font-size:9px;font-weight:700;color:${batColor};
          background:#0d1117;border:1px solid ${batColor}40;
          padding:0 4px;border-radius:3px;white-space:nowrap;
        ">${Math.round(drone.battery_charge)}%</div>
      </div>
    `,
  })
}

// ── Depot icon ──────────────────────────────────────────────────────────
function createDepotIcon(depot, primary) {
  const color = primary ? '#34d399' : '#a78bfa'
  const s = primary ? 38 : 32
  return L.divIcon({
    className: '',
    iconSize: [s, s],
    iconAnchor: [s / 2, s / 2],
    html: `
      <div style="
        width:${s}px;height:${s}px;border-radius:8px;
        border:2px solid ${color};background:${color}15;
        display:flex;align-items:center;justify-content:center;
      ">
        <svg width="${primary ? 18 : 14}" height="${primary ? 18 : 14}"
          viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2">
          <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
          <polyline points="9 22 9 12 15 12 15 22"/>
        </svg>
      </div>
    `,
  })
}

// ── Destination marker ──────────────────────────────────────────────────
function createDestIcon(order) {
  const color = order.priority === 'medical' ? '#f87171' : '#fbbf24'
  return L.divIcon({
    className: '',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `
      <div style="
        width:22px;height:22px;border-radius:50%;
        border:2px solid ${color};background:${color}18;
        display:flex;align-items:center;justify-content:center;font-size:10px;
      ">📦</div>
    `,
  })
}

// ── Pad dots ────────────────────────────────────────────────────────────
function PadInfo({ pads }) {
  const colors = { available: '#34d399', occupied: '#f87171', reserved: '#fbbf24', blocked: '#94a3b8' }
  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
      {pads.map(pad => (
        <div key={pad.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <div style={{ width: 7, height: 7, borderRadius: '50%', background: colors[pad.status] || '#94a3b8' }} />
          <span style={{ fontSize: 10, color: '#94a3b8' }}>{pad.id.split('-').pop()}</span>
        </div>
      ))}
    </div>
  )
}

// ── Component ───────────────────────────────────────────────────────────
export default function MissionMap({ drones, depots, orders, weatherCells }) {
  const droneList  = useMemo(() => drones  ? Object.values(drones)  : [], [drones])
  const depotList  = useMemo(() => depots  ? Object.values(depots)  : [], [depots])
  const orderList  = useMemo(() => orders  ? Object.values(orders).filter(o => ['dispatched','in_transit'].includes(o.status)) : [], [orders])
  const activeDrones = useMemo(() => droneList.filter(d => !['idle','battery_swap'].includes(d.status)), [droneList])

  const tipStyle = { background: '#13171f', border: '1px solid #1e2535', borderRadius: 4, padding: '2px 8px', fontSize: 10, fontWeight: 600 }

  return (
    <MapContainer center={CENTER} zoom={ZOOM} zoomControl style={{ width: '100%', height: '100%' }}>
      <TileLayer
        url="https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png"
        attribution='&copy; <a href="https://stadiamaps.com/">Stadia</a> &copy; OpenMapTiles &copy; OSM'
        maxZoom={20}
      />

      {/* Weather cells */}
      {weatherCells?.filter(c => c.active).map(cell => (
        <Circle key={cell.id}
          center={[cell.position.lat, cell.position.lon]}
          radius={cell.radius_km * 1000}
          pathOptions={{ color: '#fb923c', fillColor: '#fb923c', fillOpacity: 0.07, weight: 1.5, dashArray: '5 4' }}
        >
          <Tooltip permanent direction="top">
            <div style={{ ...tipStyle, color: '#fb923c' }}>
              🌪 {cell.wind_speed_kmh} km/h
            </div>
          </Tooltip>
        </Circle>
      ))}

      {/* Depot markers */}
      {depotList.map((depot, i) => (
        <Marker key={depot.id} position={[depot.position.lat, depot.position.lon]} icon={createDepotIcon(depot, i === 0)}>
          <Popup>
            <div style={{ fontFamily: 'Inter,sans-serif', minWidth: 180 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: i === 0 ? '#34d399' : '#a78bfa', marginBottom: 6 }}>{depot.name}</div>
              <div style={{ fontSize: 10, color: '#94a3b8' }}>Pads:</div>
              <PadInfo pads={depot.pads} />
              <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 6 }}>
                Swap stations: {depot.battery_swap_stations} · Queued: {depot.queued_outbound?.length || 0}
              </div>
            </div>
          </Popup>
          <Tooltip direction="top" offset={[0, -20]}>
            <div style={{ ...tipStyle, color: i === 0 ? '#34d399' : '#a78bfa' }}>{depot.name}</div>
          </Tooltip>
        </Marker>
      ))}

      {/* Flight paths */}
      {activeDrones.map(drone => {
        if (!drone.waypoints?.length) return null
        const color  = drone.route_color || '#38bdf8'
        const cur    = [drone.position.lat, drone.position.lon]
        const ahead  = [cur, ...drone.waypoints.slice(drone.waypoint_index).map(w => [w.lat, w.lon])]
        const behind = [...drone.waypoints.slice(0, drone.waypoint_index + 1).map(w => [w.lat, w.lon]), cur]
        return (
          <div key={`path-${drone.id}`}>
            <Polyline positions={ahead}  pathOptions={{ color, weight: 1.5, opacity: 0.35, dashArray: '6 4' }} />
            {behind.length > 1 && <Polyline positions={behind} pathOptions={{ color, weight: 2.5, opacity: 0.75 }} />}
          </div>
        )
      })}

      {/* Drone markers */}
      {droneList.map(drone => (
        <Marker key={drone.id} position={[drone.position.lat, drone.position.lon]} icon={createDroneIcon(drone)}>
          <Popup>
            <div style={{ fontFamily: 'Inter,sans-serif', minWidth: 190 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#38bdf8', marginBottom: 4 }}>{drone.name}</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 10px', fontSize: 10 }}>
                {[
                  ['Status',  drone.status.replace('_',' ').toUpperCase()],
                  ['Battery', drone.battery_charge.toFixed(1) + '%'],
                  ['SoH',     drone.battery_soh + '%'],
                  ['Alt',     drone.altitude_m.toFixed(0) + 'm'],
                  ['Speed',   drone.speed_kmh + ' km/h'],
                  ['Payload', drone.current_payload_kg + ' kg'],
                ].map(([k, v]) => (
                  <div key={k}>
                    <span style={{ color: '#475569' }}>{k}: </span>
                    <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </Popup>
          <Tooltip direction="right" offset={[20, 0]}>
            <div style={{ ...tipStyle, color: '#38bdf8' }}>
              {drone.name} · {drone.battery_charge.toFixed(0)}%
            </div>
          </Tooltip>
        </Marker>
      ))}

      {/* Order destinations */}
      {orderList.map(order => (
        <Marker key={order.id} position={[order.destination.lat, order.destination.lon]} icon={createDestIcon(order)}>
          <Tooltip direction="bottom" offset={[0, 10]}>
            <div style={{ ...tipStyle, color: '#fbbf24' }}>
              {order.destination_label} · {order.weight_kg}kg
            </div>
          </Tooltip>
        </Marker>
      ))}
    </MapContainer>
  )
}
