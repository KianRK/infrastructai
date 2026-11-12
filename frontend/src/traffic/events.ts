import type { StreamEvent } from '../api/types.ts'

export type Connection = 'connecting' | 'live' | 'interrupted'

interface Handlers {
  onEvent: (event: StreamEvent) => void
  onConnection: (state: Connection) => void
  /** The server refused the connection for good (e.g. the session expired). */
  onClosed: () => void
}

/**
 * Subscribes to the analysis results (server-sent events). The server ends the
 * connection every two minutes; EventSource reconnects by itself, and the page keeps
 * showing results from its buffer in between. Returns a function that unsubscribes.
 */
export function subscribeToTraffic(handlers: Handlers): () => void {
  const source = new EventSource('/api/traffic/events')
  source.onopen = () => {
    handlers.onConnection('live')
  }
  source.onmessage = (message: MessageEvent<string>) => {
    handlers.onEvent(JSON.parse(message.data) as StreamEvent)
  }
  source.onerror = () => {
    // CONNECTING: the browser is retrying. CLOSED: it gave up (an HTTP error status).
    if (source.readyState === EventSource.CLOSED) handlers.onClosed()
    else handlers.onConnection('interrupted')
  }
  return () => {
    source.close()
  }
}
