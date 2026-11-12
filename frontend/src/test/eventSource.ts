import { vi } from 'vitest'

/** Stands in for the browser's EventSource (jsdom has none); tests push messages. */
export class FakeEventSource {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  static instances: FakeEventSource[] = []

  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((message: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  open(): void {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
  }

  send(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  /** The connection failed; `final` means the browser will not retry. */
  fail(final: boolean): void {
    this.readyState = final ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING
    this.onerror?.()
  }

  close(): void {
    this.readyState = FakeEventSource.CLOSED
  }
}

export function mockEventSource(): typeof FakeEventSource {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  return FakeEventSource
}
