import { useEffect, useRef, useState } from 'react'
import type { StreamEvent, StreamInfo } from '../api/types.ts'
import { drift, livePosition, type Timeline } from '../traffic/timeline.ts'

interface Props {
  stream: StreamInfo
  /** performance.now() when the stream list arrived: the reference for the clock. */
  receivedAt: number
  delaySeconds: number
  timeline: Timeline
  classes: string[]
}

/** The video is moved back onto the server's clock when it is further off than this. */
const MAX_DRIFT_SECONDS = 0.5
const TICK_MS = 100

const LABELS: Record<string, string> = { train: 'tram / train' }

function display(label: string): string {
  return LABELS[label] ?? label
}

function percent(fraction: number): string {
  return `${(fraction * 100).toFixed(2)}%`
}

/**
 * One "camera": the video, kept on the server's clock, with the boxes of the analysis
 * result that belongs to the frame on screen, and that result's statistics beside it.
 */
export function StreamPanel({ stream, receivedAt, delaySeconds, timeline, classes }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [current, setCurrent] = useState<StreamEvent | null>(null)
  const [stats, setStats] = useState<StreamEvent['stats'] | null>(null)

  useEffect(() => {
    const tick = () => {
      const expected = livePosition(stream, receivedAt, performance.now(), delaySeconds)
      const video = videoRef.current
      let shown = expected
      if (video && video.readyState >= 1) {
        if (Math.abs(drift(expected, video.currentTime, stream.duration)) > MAX_DRIFT_SECONDS) {
          video.currentTime = expected
        }
        if (video.paused) void video.play().catch(() => undefined)
        shown = video.currentTime
      }
      const event = timeline.at(shown)
      setCurrent((previous) => (previous?.seq === event?.seq ? previous : event))
      // The numbers stay on screen when a result is missing for a moment.
      if (event) setStats((previous) => (previous === event.stats ? previous : event.stats))
    }
    tick()
    const timer = window.setInterval(tick, TICK_MS)
    return () => {
      window.clearInterval(timer)
    }
  }, [stream, receivedAt, delaySeconds, timeline])

  const known = [...new Set([...classes, ...Object.keys(stats?.counted ?? {})])]
  const total = (values: Record<string, number>) => Object.values(values).reduce((a, b) => a + b, 0)

  return (
    <section className="card stream" aria-label={stream.title}>
      <div>
        <div className="stream-view" style={{ aspectRatio: String(stream.aspect_ratio) }}>
          {stream.video_url ? (
            <video ref={videoRef} src={stream.video_url} muted loop playsInline preload="auto" />
          ) : (
            <p className="placeholder muted">No video in this build (dummy models)</p>
          )}
          <span className="live">Live analysis</span>
          {current?.objects.map((object) => {
            const [xMin, yMin, xMax, yMax] = object.box
            return (
              <div
                key={object.id}
                className="tbox"
                data-label={object.label}
                data-testid="traffic-box"
                style={{
                  left: percent(xMin),
                  top: percent(yMin),
                  width: percent(xMax - xMin),
                  height: percent(yMax - yMin),
                }}
              >
                <span className={`tag${yMin < 0.08 ? ' inside' : ''}`}>
                  {display(object.label)}
                </span>
              </div>
            )
          })}
        </div>
        <p className="muted credit">
          {stream.source_url ? (
            <>
              Video:{' '}
              <a href={stream.source_url} target="_blank" rel="noreferrer">
                {stream.attribution}
              </a>
              , {stream.licence}. Replayed in a loop as a stand-in for a camera feed.
            </>
          ) : (
            'Synthetic objects, no camera.'
          )}
        </p>
      </div>
      <div className="stream-stats">
        <h2>{stream.title}</h2>
        <p className="muted">{stream.location}</p>
        {stats ? (
          <>
            <dl className="figures">
              <div>
                <dt>In view</dt>
                <dd>{total(stats.in_view)}</dd>
              </div>
              <div>
                <dt>New per minute</dt>
                <dd>{stats.per_minute}</dd>
              </div>
              <div>
                <dt>Counted</dt>
                <dd>{total(stats.counted)}</dd>
              </div>
            </dl>
            <table>
              <thead>
                <tr>
                  <th scope="col">Road user</th>
                  <th scope="col">In view</th>
                  <th scope="col">Counted</th>
                </tr>
              </thead>
              <tbody>
                {known.map((label) => (
                  <tr key={label}>
                    <th scope="row">
                      <span className="swatch" data-label={label} />
                      {display(label)}
                    </th>
                    <td>{stats.in_view[label] ?? 0}</td>
                    <td>{stats.counted[label] ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              {stats.analysis_fps.toFixed(1)} frames analysed per second,{' '}
              {Math.round(stats.inference_ms)} ms per frame
              {stats.dropped_frames > 0 ? `, ${String(stats.dropped_frames)} frames skipped` : ''}.
              Counts are estimates: an object that is hidden for a while is counted again.
            </p>
          </>
        ) : (
          <p role="status" className="loading">
            Waiting for the first results…
          </p>
        )}
      </div>
    </section>
  )
}
