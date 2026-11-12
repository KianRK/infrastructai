import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
})

// jsdom has no object URLs; the app only needs a stable string for <img src>.
URL.createObjectURL = () => 'blob:preview'
URL.revokeObjectURL = () => undefined

// jsdom does not play media; the page only needs play() to exist. (Not defined in test
// files that run without a DOM.)
if (typeof HTMLMediaElement !== 'undefined') {
  HTMLMediaElement.prototype.play = () => Promise.resolve()
}

afterEach(() => {
  vi.unstubAllGlobals()
})
