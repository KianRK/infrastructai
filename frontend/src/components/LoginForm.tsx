import { useState } from 'react'
import type { SyntheticEvent } from 'react'
import { login } from '../api/client.ts'

interface Props {
  onLoggedIn: () => void
  notice?: string | null
}

export function LoginForm({ onLoggedIn, notice }: Props) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: SyntheticEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(password)
      onLoggedIn()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Login failed.')
      setBusy(false)
    }
  }

  return (
    <form className="card login" onSubmit={(event) => void submit(event)}>
      <h2>Log in</h2>
      <p className="muted">This demo is password protected.</p>
      {notice ? <p className="notice">{notice}</p> : null}
      <label htmlFor="password">Password</label>
      <input
        id="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => {
          setPassword(event.target.value)
        }}
        required
        autoFocus
      />
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={busy || password.length === 0}>
        {busy ? 'Logging in…' : 'Log in'}
      </button>
    </form>
  )
}
