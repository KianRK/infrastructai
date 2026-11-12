import { vi } from 'vitest'

type Reply = Response | Promise<Response> | (() => Response | Promise<Response>)

export function json(body: unknown, status = 200, headers?: Record<string, string>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

export function status(code: number, headers?: Record<string, string>): Response {
  return new Response(null, { status: code, headers })
}

/**
 * Replaces fetch with a table of "METHOD /path" -> reply. A request that is not in the
 * table fails the test, so components cannot call endpoints the test did not expect.
 */
export function mockApi(routes: Record<string, Reply>) {
  const calls: { key: string; init: RequestInit | undefined }[] = []
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : input.toString()
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push({ key, init })
    if (!(key in routes)) return Promise.reject(new Error(`unexpected request: ${key}`))
    const reply = routes[key]
    return Promise.resolve(typeof reply === 'function' ? reply() : reply)
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, count: (key: string) => calls.filter((call) => call.key === key).length }
}
