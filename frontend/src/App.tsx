import { useCallback, useEffect, useState } from 'react'
import { analyze, ApiError, hasSession, logout } from './api/client.ts'
import type { AnalysisResponse } from './api/types.ts'
import { LoginForm } from './components/LoginForm.tsx'
import { ResultView } from './components/ResultView.tsx'
import { TrafficPage } from './components/TrafficPage.tsx'
import { UploadPanel } from './components/UploadPanel.tsx'

type Session = 'checking' | 'anonymous' | 'authenticated' | 'unreachable'
type Page = 'photo' | 'traffic'

function pageFromHash(): Page {
  return window.location.hash === '#traffic' ? 'traffic' : 'photo'
}

interface Analysis {
  imageUrl: string
  result: AnalysisResponse | null
  error: string | null
}

function App() {
  const [session, setSession] = useState<Session>('checking')
  const [notice, setNotice] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [page, setPage] = useState<Page>(pageFromHash)
  const busy = analysis !== null && analysis.result === null && analysis.error === null

  useEffect(() => {
    let cancelled = false
    hasSession().then(
      (ok) => {
        if (!cancelled) setSession(ok ? 'authenticated' : 'anonymous')
      },
      () => {
        if (!cancelled) setSession('unreachable')
      },
    )
    return () => {
      cancelled = true
    }
  }, [])

  // The page is part of the address (#traffic), so it survives a reload and can be linked.
  useEffect(() => {
    const onHashChange = () => {
      setPage(pageFromHash())
    }
    window.addEventListener('hashchange', onHashChange)
    return () => {
      window.removeEventListener('hashchange', onHashChange)
    }
  }, [])

  const sessionExpired = useCallback((message: string) => {
    setAnalysis(null)
    setNotice(message)
    setSession('anonymous')
  }, [])

  // Release the previous preview when it is replaced or the page goes away.
  const imageUrl = analysis?.imageUrl
  useEffect(() => {
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl)
    }
  }, [imageUrl])

  async function run(file: File) {
    const current: Analysis = { imageUrl: URL.createObjectURL(file), result: null, error: null }
    setAnalysis(current)
    try {
      const result = await analyze(file)
      setAnalysis({ ...current, result })
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        sessionExpired(caught.message)
        return
      }
      const message = caught instanceof Error ? caught.message : 'The analysis failed.'
      setAnalysis({ ...current, error: message })
    }
  }

  async function signOut() {
    try {
      await logout()
    } finally {
      setAnalysis(null)
      setNotice(null)
      setSession('anonymous')
    }
  }

  return (
    <>
      <header>
        <h1>RoadScan</h1>
        <p className="muted">Road damage detection and live traffic analysis</p>
        {session === 'authenticated' ? (
          <button type="button" className="link" onClick={() => void signOut()}>
            Log out
          </button>
        ) : null}
      </header>
      <main>
        {session === 'checking' ? <p role="status">Loading…</p> : null}
        {session === 'unreachable' ? (
          <p className="error" role="alert">
            The service is not reachable right now. The demo cluster may be switched off; please
            try again later.
          </p>
        ) : null}
        {session === 'anonymous' ? (
          <LoginForm
            notice={notice}
            onLoggedIn={() => {
              setNotice(null)
              setSession('authenticated')
            }}
          />
        ) : null}
        {session === 'authenticated' ? (
          <nav aria-label="Pages">
            <a href="#photo" aria-current={page === 'photo' ? 'page' : undefined}>
              Photo analysis
            </a>
            <a href="#traffic" aria-current={page === 'traffic' ? 'page' : undefined}>
              Live traffic
            </a>
          </nav>
        ) : null}
        {session === 'authenticated' && page === 'traffic' ? (
          <TrafficPage onUnauthorized={sessionExpired} />
        ) : null}
        {session === 'authenticated' && page === 'photo' ? (
          <>
            <UploadPanel disabled={busy} onFile={(file) => void run(file)} />
            {analysis?.error ? (
              <p className="error" role="alert">
                {analysis.error}
              </p>
            ) : null}
            {analysis && !analysis.error ? (
              <ResultView imageUrl={analysis.imageUrl} result={analysis.result} />
            ) : null}
          </>
        ) : null}
      </main>
      <footer className="muted">
        Damage detector trained on RDD2022. Results are automated estimates, not an inspection.
      </footer>
    </>
  )
}

export default App
