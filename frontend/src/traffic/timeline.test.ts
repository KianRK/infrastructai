import { expect, test } from 'vitest'
import { streamEvent, streamList } from '../test/fixtures.ts'
import { drift, livePosition, MAX_RESULT_AGE, Timeline } from './timeline.ts'

function timeline(...times: number[]): Timeline {
  const result = new Timeline()
  times.forEach((t, index) => {
    result.push(streamEvent({ t, seq: index + 1 }))
  })
  return result
}

test('picks the newest result at or before the frame on screen', () => {
  const results = timeline(4.0, 4.2, 4.4, 4.6)

  expect(results.at(4.45)?.t).toBe(4.4)
  expect(results.at(4.2)?.t).toBe(4.2)
  expect(results.at(3.9)).toBeNull() // nothing for frames before the first result
})

test('does not show stale results', () => {
  const results = timeline(4.0)

  expect(results.at(4.0 + MAX_RESULT_AGE)).not.toBeNull()
  expect(results.at(4.0 + MAX_RESULT_AGE + 0.1)).toBeNull()
})

test('after the video starts over, results of the previous round are ignored', () => {
  const results = timeline(119.6, 119.8, 0.0, 0.2)

  expect(results.at(0.1)?.seq).toBe(3)
  expect(results.at(119.9)?.seq).toBe(2) // the video is still at the end of the round
})

test('keeps a bounded number of results', () => {
  const results = new Timeline()
  for (let n = 0; n < 500; n++) results.push(streamEvent({ t: n * 0.2, seq: n }))

  expect(results.at(0.1)).toBeNull() // long gone
  expect(results.at(99.85)?.t).toBeCloseTo(99.8)
})

test('the live position follows the server clock, behind by the display delay', () => {
  const stream = { ...streamList.streams[0], position: 10, duration: 120 }

  expect(livePosition(stream, 1000, 1000, 1.5)).toBeCloseTo(8.5)
  expect(livePosition(stream, 1000, 4000, 1.5)).toBeCloseTo(11.5)
  expect(livePosition(stream, 1000, 1000 + 115_000, 1.5)).toBeCloseTo(3.5) // next round
  expect(livePosition({ ...stream, position: 0.5 }, 0, 0, 1.5)).toBeCloseTo(119) // wraps back
})

test('drift is measured around the loop', () => {
  expect(drift(10, 9.5, 120)).toBeCloseTo(0.5)
  expect(drift(9.5, 10, 120)).toBeCloseTo(-0.5)
  expect(drift(0.2, 119.9, 120)).toBeCloseTo(0.3)
  expect(drift(119.9, 0.2, 120)).toBeCloseTo(-0.3)
})
