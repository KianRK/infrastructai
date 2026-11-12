import type { AnalysisResponse } from './types.ts'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const STATUS_MESSAGES: Partial<Record<number, string>> = {
  400: 'The file could not be read as an image.',
  401: 'Your session has expired. Please log in again.',
  413: 'The image is too large.',
  415: 'This file type is not supported.',
  429: 'Too many requests. Please wait a moment and try again.',
  503: 'The service is starting up or busy. Please try again shortly.',
}

function retryHint(response: Response): string {
  const seconds = Number(response.headers.get('Retry-After'))
  return Number.isFinite(seconds) && seconds > 0
    ? ` Try again in ${String(Math.ceil(seconds))} seconds.`
    : ''
}

function toError(response: Response): ApiError {
  const known = STATUS_MESSAGES[response.status]
  if (known !== undefined) {
    return new ApiError(response.status, known + (response.status === 429 ? retryHint(response) : ''))
  }
  return new ApiError(response.status, `The request failed (HTTP ${String(response.status)}).`)
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    // The session is an HttpOnly cookie; same-origin requests send it automatically.
    response = await fetch(path, { credentials: 'same-origin', ...init })
  } catch {
    throw new ApiError(0, 'The server could not be reached. Check your connection.')
  }
  if (!response.ok) throw toError(response)
  return response
}

/** Whether the browser holds a valid session cookie. */
export async function hasSession(): Promise<boolean> {
  try {
    await request('/api/auth/session')
    return true
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return false
    throw error
  }
}

export async function login(password: string): Promise<void> {
  try {
    await request('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    })
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      throw new ApiError(401, 'Wrong password.')
    }
    throw error
  }
}

export async function logout(): Promise<void> {
  await request('/api/auth/logout', { method: 'POST' })
}

export async function analyze(file: File): Promise<AnalysisResponse> {
  const body = new FormData()
  body.append('file', file)
  const response = await request('/api/analyze', { method: 'POST', body })
  return (await response.json()) as AnalysisResponse
}
