import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
})

// jsdom has no object URLs; the app only needs a stable string for <img src>.
URL.createObjectURL = () => 'blob:preview'
URL.revokeObjectURL = () => undefined

afterEach(() => {
  vi.unstubAllGlobals()
})
