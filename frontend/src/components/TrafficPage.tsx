import { useEffect, useState } from 'react'
import { ApiError, trafficStreams } from '../api/client.ts'
import type { StreamList } from '../api/types.ts'
import { subscribeToTraffic, type Connection } from '../traffic/events.ts'
import { Timeline } from '../traffic/timeline.ts'
import { StreamPanel } from './StreamPanel.tsx'

interface Props {
  /** The session ended: the app shows the login form again. */
  onUnauthorized: (message: string) => void
}

interface Loaded {
  list: StreamList
  /** performance.now() when the list arrived: the reference for the stream clock. */
  receivedAt: number
  /** Recent results per stream id; filled by the event subscription. */
  timelines: Map<string, Timeline>
}

/** After the server refused the event stream, ask again this much later. */
const RETRY_MS = 5000

/**
 * Two video streams analysed on the server while somebody watches. The page asks once
 * where the server's clock is, plays the videos at that position and draws the results
 * it receives as server-sent events.
 */
export function TrafficPage({ onUnauthorized }: Props) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [connection, setConnection] = useState<Connection>('connecting')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    let unsubscribe: (() => void) | undefined
    let retry: number | undefined
    const again = () => {
      retry = window.setTimeout(() => {
        setAttempt((n) => n + 1)
      }, RETRY_MS)
    }

    trafficStreams().then(
      (list) => {
        if (cancelled) return
        const timelines = new Map(list.streams.map((stream) => [stream.id, new Timeline()]))
        setLoaded({ list, receivedAt: performance.now(), timelines })
        setError(null)
        unsubscribe = subscribeToTraffic({
          onEvent: (event) => timelines.get(event.stream)?.push(event),
          onConnection: setConnection,
          // Refused (too many viewers, expired session, restart): loading the list
          // again tells which, and resynchronises the clock.
          onClosed: () => {
            setConnection('interrupted')
            again()
          },
        })
      },
      (caught: unknown) => {
        if (cancelled) return
        if (caught instanceof ApiError && caught.status === 401) {
          onUnauthorized(caught.message)
          return
        }
        setError(caught instanceof Error ? caught.message : 'The streams could not be loaded.')
        again()
      },
    )
    return () => {
      cancelled = true
      unsubscribe?.()
      window.clearTimeout(retry)
    }
  }, [attempt, onUnauthorized])

  if (!loaded) {
    return error ? (
      <p className="error" role="alert">
        {error}
      </p>
    ) : (
      <p role="status" className="loading">
        Loading the streams…
      </p>
    )
  }

  const { list, receivedAt, timelines } = loaded
  return (
    <>
      <p className="muted">
        Road users are detected and tracked on the server, a few frames per second, for as long as
        somebody is watching. Detector: {list.detector_version}.
        {connection === 'interrupted' ? ' Reconnecting…' : ''}
      </p>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {list.streams.map((stream) => {
        const timeline = timelines.get(stream.id)
        return timeline ? (
          <StreamPanel
            key={stream.id}
            stream={stream}
            receivedAt={receivedAt}
            delaySeconds={list.delay_seconds}
            timeline={timeline}
            classes={list.classes}
          />
        ) : null
      })}
    </>
  )
}
