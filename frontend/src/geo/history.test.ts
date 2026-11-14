import { expect, test } from 'vitest'
import { analysisWithDamage, analysisWithoutDamage } from '../test/fixtures.ts'
import {
  addEntry,
  describeDamage,
  makeEntry,
  MAX_ENTRIES,
  placeEntry,
  worstRating,
} from './history.ts'

test('an entry summarises the analysis: worst severity, damage counts, uncertainty', () => {
  const entry = makeEntry(1, 'road.jpg', 'blob:1', analysisWithDamage, { lat: 50, lon: 14 }, 1000)

  expect(entry).toMatchObject({
    rating: 'moderate',
    placement: 'photo',
    needsVerification: true,
    damage: [
      { label: 'pothole', count: 1 },
      { label: 'longitudinal crack', count: 1 },
    ],
  })
  expect(describeDamage(entry)).toBe('1 pothole, 1 longitudinal crack')
})

test('a photo without damage or position', () => {
  const entry = makeEntry(2, 'clean.jpg', 'blob:2', analysisWithoutDamage, null)

  expect(worstRating(analysisWithoutDamage)).toBe('none')
  expect(entry.placement).toBeNull()
  expect(describeDamage(entry)).toBe('No damage detected')
})

test('newest entries come first and the oldest fall off beyond the limit', () => {
  let entries = [makeEntry(0, 'p0.jpg', 'blob:0', analysisWithoutDamage, null)]
  let dropped: typeof entries = []
  for (let id = 1; id <= MAX_ENTRIES; id++) {
    const entry = makeEntry(id, `p${String(id)}.jpg`, `blob:${String(id)}`, analysisWithoutDamage, null)
    ;[entries, dropped] = addEntry(entries, entry)
  }
  expect(entries).toHaveLength(MAX_ENTRIES)
  expect(entries[0].id).toBe(MAX_ENTRIES)
  expect(dropped.map((entry) => entry.id)).toEqual([0])
})

test('placing an entry by hand marks the position as manual', () => {
  const entries = [makeEntry(7, 'p.jpg', 'blob:7', analysisWithDamage, null)]
  const [placed] = placeEntry(entries, 7, { lat: 1, lon: 2 })
  expect(placed).toMatchObject({ position: { lat: 1, lon: 2 }, placement: 'manual' })
})
