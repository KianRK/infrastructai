import type { StreamEvent, StreamInfo } from '../api/types.ts'

/** A result older than this is not drawn over the video: the boxes would be stale. */
export const MAX_RESULT_AGE = 1.0
const KEEP = 60 // events; about twelve seconds at five per second

/**
 * The most recent analysis results of one stream. Results arrive a little ahead of the
 * (deliberately delayed) video; `at` picks the one that belongs to the frame on screen.
 */
export class Timeline {
  private events: StreamEvent[] = []

  push(event: StreamEvent): void {
    this.events.push(event)
    if (this.events.length > KEEP) this.events.shift()
  }

  /** The newest result for a frame at or before `videoTime`, or null if none is recent. */
  at(videoTime: number): StreamEvent | null {
    // Searched from the newest: after the video jumps back to its start, results of
    // the previous round have larger times and are skipped.
    for (let index = this.events.length - 1; index >= 0; index--) {
      const event = this.events[index]
      const age = videoTime - event.t
      if (age >= 0 && age <= MAX_RESULT_AGE) return event
    }
    return null
  }
}

/**
 * Where the video should be now: the server's clock, continued locally from the moment
 * its answer arrived, minus the display delay. Every viewer computes the same position.
 */
export function livePosition(
  stream: StreamInfo,
  receivedAt: number,
  now: number,
  delaySeconds: number,
): number {
  const position = stream.position + (now - receivedAt) / 1000 - delaySeconds
  return ((position % stream.duration) + stream.duration) % stream.duration
}

/** Signed distance from `actual` to `expected` on a loop of length `duration`. */
export function drift(expected: number, actual: number, duration: number): number {
  const difference = (((expected - actual) % duration) + duration) % duration
  return difference > duration / 2 ? difference - duration : difference
}
