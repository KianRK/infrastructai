// The photos analysed in this browser session, for the map. Kept in memory only: nothing
// is stored on the server or in the browser, and a reload starts with an empty map.

import type { AnalysisResponse, Severity } from '../api/types.ts'
import type { Position } from './exif.ts'

export const MAX_ENTRIES = 50

export type Rating = Severity | 'none'

export interface MapEntry {
  id: number
  name: string
  /** Object URL of the photo; owned by the entry and revoked when it is dropped. */
  imageUrl: string
  analysedAt: number
  position: Position | null
  /** Where the position came from: the photo's GPS data or a click on the map. */
  placement: 'photo' | 'manual' | null
  rating: Rating
  /** Detected damage types with their number of boxes, most severe type first. */
  damage: { label: string; count: number }[]
  needsVerification: boolean
}

const ORDER: Record<Rating, number> = { none: 0, low: 1, moderate: 2, high: 3 }

export function worstRating(result: AnalysisResponse): Rating {
  return result.recommendations.reduce<Rating>(
    (worst, item) => (ORDER[item.severity] > ORDER[worst] ? item.severity : worst),
    'none',
  )
}

export function makeEntry(
  id: number,
  name: string,
  imageUrl: string,
  result: AnalysisResponse,
  position: Position | null,
  now: number = Date.now(),
): MapEntry {
  return {
    id,
    name,
    imageUrl,
    analysedAt: now,
    position,
    placement: position ? 'photo' : null,
    rating: worstRating(result),
    damage: result.recommendations.map((item) => ({
      label: item.label,
      count: result.detections.filter((d) => d.damage_class === item.damage_class).length,
    })),
    needsVerification: result.recommendations.some((item) => item.needs_verification),
  }
}

/** Newest first; returns the kept entries and those that fell off the end. */
export function addEntry(entries: MapEntry[], entry: MapEntry): [MapEntry[], MapEntry[]] {
  const all = [entry, ...entries]
  return [all.slice(0, MAX_ENTRIES), all.slice(MAX_ENTRIES)]
}

export function placeEntry(entries: MapEntry[], id: number, position: Position): MapEntry[] {
  return entries.map((entry) =>
    entry.id === id ? { ...entry, position, placement: 'manual' } : entry,
  )
}

export function describeDamage(entry: MapEntry): string {
  if (entry.damage.length === 0) return 'No damage detected'
  return entry.damage
    .map(({ label, count }) => (count === 1 ? `1 ${label}` : `${String(count)} × ${label}`))
    .join(', ')
}
