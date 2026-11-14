import { useEffect, useEffectEvent, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { Position } from '../geo/exif.ts'
import { describeDamage, type MapEntry, type Rating } from '../geo/history.ts'

interface Props {
  entries: MapEntry[]
  onPlace: (id: number, position: Position) => void
}

const RATING_COLOURS: Record<Rating, string> = {
  none: '#2e8b57',
  low: '#c9a227',
  moderate: '#e07b00',
  high: '#d0342c',
}

const RATING_TEXT: Record<Rating, string> = {
  none: 'no damage',
  low: 'low severity',
  moderate: 'moderate severity',
  high: 'high severity',
}

const WORLD: L.LatLngTuple = [30, 10]

/** Popup content as DOM nodes: the file name comes from the user and is never parsed as HTML. */
function popupContent(entry: MapEntry): HTMLElement {
  const box = document.createElement('div')
  box.className = 'map-popup'
  const image = document.createElement('img')
  image.src = entry.imageUrl
  image.alt = ''
  const name = document.createElement('strong')
  name.textContent = entry.name
  const damage = document.createElement('span')
  damage.textContent = `${describeDamage(entry)} (${RATING_TEXT[entry.rating]})`
  box.append(image, name, damage)
  if (entry.needsVerification) {
    const verify = document.createElement('span')
    verify.textContent = 'Uncertain detections: verify on site.'
    box.append(verify)
  }
  return box
}

export function MapPage({ entries, onPlace }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const markers = useRef(new Map<number, L.CircleMarker>())
  const [placing, setPlacing] = useState<number | null>(null)

  // Sees the current `placing` and `onPlace` without re-creating the map.
  const onMapClick = useEffectEvent((latlng: L.LatLng) => {
    if (placing === null) return
    onPlace(placing, { lat: latlng.lat, lon: latlng.wrap().lng })
    setPlacing(null)
  })

  // One Leaflet map for the lifetime of the page.
  useEffect(() => {
    if (!container.current) return
    const created = L.map(container.current, { center: WORLD, zoom: 2, worldCopyJump: true })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      // The site sends no Referer at all; OpenStreetMap's tile policy asks for one, so the
      // tile requests carry the origin (never the full address).
      referrerPolicy: 'strict-origin-when-cross-origin',
    }).addTo(created)
    created.on('click', (event: L.LeafletMouseEvent) => {
      onMapClick(event.latlng)
    })
    layer.current = L.layerGroup().addTo(created)
    map.current = created
    const ownMarkers = markers.current
    return () => {
      created.remove()
      map.current = null
      layer.current = null
      ownMarkers.clear()
    }
  }, [])

  // Markers follow the entries; the view fits all of them when their number changes.
  const placed = entries.filter((entry) => entry.position !== null)
  const placedKey = JSON.stringify(placed.map((entry) => [entry.id, entry.position, entry.rating]))
  useEffect(() => {
    const group = layer.current
    if (!group || !map.current) return
    group.clearLayers()
    markers.current.clear()
    for (const entry of placed) {
      if (!entry.position) continue
      const marker = L.circleMarker([entry.position.lat, entry.position.lon], {
        radius: 9,
        color: '#ffffff',
        weight: 2,
        fillColor: RATING_COLOURS[entry.rating],
        fillOpacity: 0.9,
      }).bindPopup(popupContent(entry))
      marker.addTo(group)
      markers.current.set(entry.id, marker)
    }
    if (placed.length === 1 && placed[0].position) {
      map.current.setView([placed[0].position.lat, placed[0].position.lon], 15)
    } else if (placed.length > 1) {
      const bounds = L.latLngBounds(
        placed.flatMap((entry) => (entry.position ? [[entry.position.lat, entry.position.lon] as L.LatLngTuple] : [])),
      )
      map.current.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 })
    }
    // placedKey stands for `placed`: it changes exactly when a marker has to change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [placedKey])

  function show(entry: MapEntry) {
    const marker = markers.current.get(entry.id)
    if (!marker || !map.current) return
    map.current.setView(marker.getLatLng(), Math.max(map.current.getZoom(), 15))
    marker.openPopup()
  }

  function placeAtCentre(id: number) {
    if (!map.current) return
    const centre = map.current.getCenter().wrap()
    onPlace(id, { lat: centre.lat, lon: centre.lng })
    setPlacing(null)
  }

  return (
    <section className="map-page">
      <p className="muted">
        Photos analysed in this browser session. The position comes from the photo&apos;s GPS
        data, read in the browser; photos without it can be placed by hand. Nothing is stored:
        reloading the page empties the map.
      </p>
      {placing !== null ? (
        <p className="placing" role="status">
          Click the map where the photo was taken, or{' '}
          <button type="button" className="link" onClick={() => { placeAtCentre(placing); }}>
            use the centre of the map
          </button>{' '}
          <button type="button" className="link" onClick={() => { setPlacing(null); }}>
            cancel
          </button>
        </p>
      ) : null}
      {/* Leaflet adds its own classes to the element it draws into, so React must never
          set that element's className: the state class goes on a wrapper. */}
      <div className={`map-frame${placing !== null ? ' placing' : ''}`}>
        <div ref={container} className="map" role="region" aria-label="Map of analysed photos" />
      </div>
      {entries.length === 0 ? (
        <p className="muted">No photos analysed yet. Analyse one on the Photo analysis page.</p>
      ) : (
        <ul className="map-list" aria-label="Analysed photos">
          {entries.map((entry) => (
            <li key={entry.id}>
              <span
                className="dot"
                style={{ background: RATING_COLOURS[entry.rating] }}
                aria-hidden="true"
              />
              <div>
                <strong>{entry.name}</strong>
                <span className="muted">
                  {' '}
                  {new Date(entry.analysedAt).toLocaleTimeString()} · {RATING_TEXT[entry.rating]}
                </span>
                <p>{describeDamage(entry)}</p>
                <p className="muted">
                  {entry.placement === 'photo'
                    ? 'Position from the photo'
                    : entry.placement === 'manual'
                      ? 'Placed by hand'
                      : 'No position in the photo'}
                </p>
              </div>
              <div className="map-actions">
                {entry.position ? (
                  <button type="button" className="link" onClick={() => { show(entry); }}>
                    Show
                  </button>
                ) : null}
                {entry.placement !== 'photo' ? (
                  <button type="button" className="link" onClick={() => { setPlacing(entry.id); }}>
                    {entry.position ? 'Move' : 'Place on map'}
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
