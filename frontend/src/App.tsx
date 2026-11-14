import { useCallback, useEffect, useRef, useState } from 'react'
import { analyze, ApiError, hasSession, logout } from './api/client.ts'
import type { AnalysisResponse } from './api/types.ts'
import { LoginForm } from './components/LoginForm.tsx'
import { MapPage } from './components/MapPage.tsx'
import { ResultView } from './components/ResultView.tsx'
import { TrafficPage } from './components/TrafficPage.tsx'
import { UploadPanel } from './components/UploadPanel.tsx'
import { readGpsPosition, type Position } from './geo/exif.ts'
import { addEntry, makeEntry, placeEntry, type MapEntry } from './geo/history.ts'

type Session = 'checking' | 'anonymous' | 'authenticated' | 'unreachable'
type Page = 'photo' | 'traffic' | 'map'

function pageFromHash(): Page {
  const hash = window.location.hash
  return hash === '#traffic' ? 'traffic' : hash === '#map' ? 'map' : 'photo'
}

interface Analysis {
  imageUrl: string
  result: AnalysisResponse | null
  error: string | null
  /** null: the photo carries no GPS position; undefined: not read yet. */
  position?: Position | null
}

/** The photo's GPS position, read in the browser; null when there is none. */
async function photoPosition(file: File): Promise<Position | null> {
  try {
    return readGpsPosition(await file.arrayBuffer())
  } catch {
    return null
  }
}

function App() {
  const [session, setSession] = useState<Session>('checking')
  const [notice, setNotice] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [page, setPage] = useState<Page>(pageFromHash)
  const [entries, setEntries] = useState<MapEntry[]>([])
  const nextId = useRef(1)
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

  // The map's photos belong to the session: dropped with it, their object URLs released.
  const clearEntries = useCallback(() => {
    setEntries((current) => {
      for (const entry of current) URL.revokeObjectURL(entry.imageUrl)
      return []
    })
  }, [])
  const entriesRef = useRef(entries)
  useEffect(() => {
    entriesRef.current = entries
  }, [entries])
  useEffect(() => {
    return () => {
      for (const entry of entriesRef.current) URL.revokeObjectURL(entry.imageUrl)
    }
  }, [])

  const sessionExpired = useCallback((message: string) => {
    clearEntries()
    setAnalysis(null)
    setNotice(message)
    setSession('anonymous')
  }, [clearEntries])

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
      const [result, position] = await Promise.all([analyze(file), photoPosition(file)])
      setAnalysis({ ...current, result, position })
      const entry = makeEntry(nextId.current++, file.name, URL.createObjectURL(file), result, position)
      setEntries((existing) => {
        const [kept, dropped] = addEntry(existing, entry)
        for (const old of dropped) URL.revokeObjectURL(old.imageUrl)
        return kept
      })
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
      clearEntries()
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
            <a href="#map" aria-current={page === 'map' ? 'page' : undefined}>
              Map
            </a>
            <a href="#traffic" aria-current={page === 'traffic' ? 'page' : undefined}>
              Live traffic
            </a>
          </nav>
        ) : null}
        {session === 'authenticated' && page === 'map' ? (
          <MapPage
            entries={entries}
            onPlace={(id, position) => {
              setEntries((existing) => placeEntry(existing, id, position))
            }}
          />
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
            {analysis?.result && analysis.position !== undefined ? (
              <p className="muted location">
                {analysis.position
                  ? 'The photo carries a GPS position; it is shown on the '
                  : 'The photo carries no GPS position; you can place it on the '}
                <a href="#map">map</a>.
              </p>
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
