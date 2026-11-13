// Load test of the photo analysis (POST /api/analyze) with k6. Run through `make loadtest`;
// see README.md in this directory.
//
// Every virtual user logs in once and then uploads photos from PHOTO_FILES (mounted at
// /photos). The arrival rate, not the number of users, is controlled: analyses start at
// the rate of the selected profile whether earlier ones have finished or not, the way
// independent users would arrive.

import http from 'k6/http'
import { check } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8080').replace(/\/$/, '')
const PASSWORD = __ENV.ROADSCAN_DEMO_PASSWORD
const PROFILE = __ENV.PROFILE || 'ramp'

const photos = (__ENV.PHOTO_FILES || '')
  .split(',')
  .filter((name) => name)
  .map((name) => ({ name, data: open(`/photos/${name}`, 'b') }))

// Analyses started per minute. Each stage holds its rate for `duration`.
const PROFILES = {
  // Checks the script and the deployment: a handful of analyses.
  smoke: [{ target: 4, duration: '1m' }],
  // Steps up until the application is saturated.
  ramp: [
    { target: 6, duration: '2m' },
    { target: 12, duration: '2m' },
    { target: 24, duration: '2m' },
    { target: 36, duration: '2m' },
    { target: 48, duration: '2m' },
  ],
}

function stagesFor(profile) {
  const steps = PROFILES[profile]
  if (!steps) throw new Error(`unknown PROFILE ${profile}; use one of ${Object.keys(PROFILES)}`)
  // ramping-arrival-rate moves linearly between targets: a 5 s ramp, then the plateau.
  return steps.flatMap((step) => [
    { target: step.target, duration: '5s' },
    { target: step.target, duration: step.duration },
  ])
}

export const options = {
  scenarios: {
    analyze: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1m',
      stages: stagesFor(PROFILE),
      preAllocatedVUs: 10,
      maxVUs: 80,
    },
  },
  // Reported, not enforced: the point is to find where the limits are.
  thresholds: {
    analysis_ok: [{ threshold: 'rate>0', abortOnFail: false }],
  },
  summaryTrendStats: ['min', 'med', 'p(90)', 'p(95)', 'max', 'count'],
}

const analysisOk = new Rate('analysis_ok')
const analysisSeconds = new Trend('analysis_seconds')
const answers = new Counter('analysis_answers')

export function setup() {
  if (!PASSWORD) throw new Error('ROADSCAN_DEMO_PASSWORD is not set')
  if (photos.length === 0) throw new Error('no photos: set PHOTOS to a directory with JPEG/PNG files')
  const health = http.get(`${BASE_URL}/api/healthz`)
  if (health.status !== 200) throw new Error(`${BASE_URL} is not healthy: ${health.status}`)
}

let loggedIn = false

export default function () {
  if (!loggedIn) {
    const login = http.post(`${BASE_URL}/api/auth/login`, JSON.stringify({ password: PASSWORD }), {
      headers: { 'Content-Type': 'application/json' },
      tags: { name: 'login' },
    })
    check(login, { 'login 204': (r) => r.status === 204 })
    loggedIn = login.status === 204
    if (!loggedIn) return
  }

  const photo = photos[Math.floor(Math.random() * photos.length)]
  const type = photo.name.endsWith('.png') ? 'image/png' : 'image/jpeg'
  const response = http.post(
    `${BASE_URL}/api/analyze`,
    { file: http.file(photo.data, photo.name, type) },
    { timeout: '200s', tags: { name: 'analyze' } },
  )
  const ok = response.status === 200
  let source = 'none'
  if (ok) {
    source = response.json('description_source')
    analysisSeconds.add(response.timings.duration / 1000, { source })
  }
  if (response.status === 401) loggedIn = false // session expired: log in again next time
  analysisOk.add(ok)
  answers.add(1, { status: String(response.status), source })
  check(response, { 'analyze 200': () => ok })
}
