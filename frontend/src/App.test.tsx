import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import App from './App.tsx'
import { mockEventSource } from './test/eventSource.ts'
import {
  analysisWithDamage,
  analysisWithoutDamage,
  imageFile,
  streamList,
} from './test/fixtures.ts'
import { json, mockApi, status } from './test/server.ts'

const LOGGED_IN = { 'GET /api/auth/session': json({ authenticated: true }) }

async function upload(file: File) {
  // applyAccept: false, so files of the wrong type reach our own validation.
  const user = userEvent.setup({ applyAccept: false })
  await user.upload(await screen.findByLabelText('Road image'), file)
  return user
}

test('shows the login form without a session and the upload after logging in', async () => {
  const api = mockApi({
    'GET /api/auth/session': status(401),
    'POST /api/auth/login': status(204),
  })
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Password'), 'demo-secret')
  await user.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('button', { name: 'Choose image' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  const login = api.calls.find((call) => call.key === 'POST /api/auth/login')
  expect(login?.init?.body).toBe(JSON.stringify({ password: 'demo-secret' }))
})

test('a wrong password shows an error and keeps the form', async () => {
  mockApi({ 'GET /api/auth/session': status(401), 'POST /api/auth/login': status(401) })
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Password'), 'nope')
  await user.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong password.')
  expect(screen.getByLabelText('Password')).toBeInTheDocument()
})

test('too many login attempts show the wait time from the server', async () => {
  mockApi({
    'GET /api/auth/session': status(401),
    'POST /api/auth/login': status(429, { 'Retry-After': '42' }),
  })
  const user = userEvent.setup()
  render(<App />)

  await user.type(await screen.findByLabelText('Password'), 'x')
  await user.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Try again in 42 seconds.')
})

test('an existing session skips the login form', async () => {
  mockApi(LOGGED_IN)
  render(<App />)
  expect(await screen.findByRole('button', { name: 'Choose image' })).toBeInTheDocument()
})

test('explains when the backend is not reachable', async () => {
  mockApi({ 'GET /api/auth/session': () => Promise.reject(new TypeError('network')) })
  render(<App />)
  expect(await screen.findByRole('alert')).toHaveTextContent('not reachable')
})

test('shows a loading state, then boxes, labels and the description', async () => {
  let finish: (response: Response) => void = () => undefined
  const pending = new Promise<Response>((resolve) => {
    finish = resolve
  })
  mockApi({ ...LOGGED_IN, 'POST /api/analyze': pending })
  render(<App />)

  await upload(imageFile())

  expect(await screen.findByRole('status')).toHaveTextContent('Analysing the image')
  expect(screen.getByRole('img', { name: 'Uploaded road' })).toHaveAttribute('src', 'blob:preview')
  expect(screen.getByRole('button', { name: 'Choose image' })).toBeDisabled()

  finish(json(analysisWithDamage))

  const boxes = await screen.findAllByTestId('detection-box')
  expect(boxes).toHaveLength(2)
  // Relative coordinates become percentages of the displayed image.
  expect(boxes[0]).toHaveStyle({ left: '40.00%', top: '55.00%', width: '22.00%', height: '25.00%' })
  expect(within(boxes[0]).getByText('pothole 91%')).toBeInTheDocument()
  expect(within(boxes[1]).getByText('longitudinal crack 67%')).toBeInTheDocument()
  expect(screen.getByText('One pothole and one longitudinal crack were found.')).toBeInTheDocument()
  expect(screen.getByText(/Written by a language model/)).toHaveTextContent(
    'Model: qwen2.5-1.5b-instruct-q4_k_m.',
  )
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Choose image' })).toBeEnabled()
})

test('an image without damage shows no boxes and says so', async () => {
  mockApi({ ...LOGGED_IN, 'POST /api/analyze': json(analysisWithoutDamage) })
  render(<App />)

  await upload(imageFile())

  expect(await screen.findByText(/No damage detected\./)).toBeInTheDocument()
  expect(screen.getByText('No road damage was detected in this image.')).toBeInTheDocument()
  expect(screen.queryByTestId('detection-box')).not.toBeInTheDocument()
})

test('an unsupported file is rejected before anything is uploaded', async () => {
  const api = mockApi(LOGGED_IN)
  render(<App />)

  await upload(imageFile('notes.pdf', 'application/pdf'))

  expect(await screen.findByRole('alert')).toHaveTextContent('JPEG, PNG or WebP')
  expect(api.count('POST /api/analyze')).toBe(0)
})

test('a server-side rejection is shown and the user can try another image', async () => {
  let attempt = 0
  mockApi({
    ...LOGGED_IN,
    'POST /api/analyze': () => (++attempt === 1 ? status(400) : json(analysisWithoutDamage)),
  })
  render(<App />)

  const user = await upload(imageFile('broken.jpg'))
  expect(await screen.findByRole('alert')).toHaveTextContent('could not be read as an image')

  await user.upload(screen.getByLabelText('Road image'), imageFile('fine.jpg'))
  expect(await screen.findByText(/No damage detected\./)).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('an expired session during analysis returns to the login form with an explanation', async () => {
  mockApi({ ...LOGGED_IN, 'POST /api/analyze': status(401) })
  render(<App />)

  await upload(imageFile())

  expect(await screen.findByLabelText('Password')).toBeInTheDocument()
  expect(screen.getByText('Your session has expired. Please log in again.')).toBeInTheDocument()
})

test('logging out returns to the login form', async () => {
  const api = mockApi({ ...LOGGED_IN, 'POST /api/auth/logout': status(204) })
  const user = userEvent.setup()
  render(<App />)

  await user.click(await screen.findByRole('button', { name: 'Log out' }))

  await waitFor(() => {
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
  })
  expect(api.count('POST /api/auth/logout')).toBe(1)
})

test('the navigation switches between photo analysis and live traffic', async () => {
  mockApi({ ...LOGGED_IN, 'GET /api/traffic/streams': json(streamList) })
  mockEventSource()
  const user = userEvent.setup()
  render(<App />)

  await user.click(await screen.findByRole('link', { name: 'Live traffic' }))
  expect(await screen.findByRole('region', { name: 'Tram junction' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Choose image' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Live traffic' })).toHaveAttribute('aria-current', 'page')

  await user.click(screen.getByRole('link', { name: 'Photo analysis' }))
  expect(await screen.findByRole('button', { name: 'Choose image' })).toBeInTheDocument()
})
