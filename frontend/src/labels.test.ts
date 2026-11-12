import { describe, expect, it } from 'vitest'

import type { Detection } from './api/types.ts'
import { placeLabels } from './labels.ts'

function detection(x_min: number, y_min: number, x_max: number, y_max: number): Detection {
  return {
    damage_class: 'D00',
    label: 'Longitudinal crack',
    confidence: 0.8,
    box: { x_min, y_min, x_max, y_max },
  }
}

describe('placeLabels', () => {
  it('keeps separate boxes on the first row', () => {
    const rows = placeLabels([detection(0.1, 0.2, 0.3, 0.4), detection(0.1, 0.6, 0.3, 0.8)])
    expect(rows.map((placement) => placement.row)).toEqual([0, 0])
  })

  it('stacks the labels of boxes that share a corner', () => {
    const rows = placeLabels([
      detection(0.2, 0.4, 0.5, 0.7),
      detection(0.21, 0.4, 0.5, 0.71),
      detection(0.2, 0.4, 0.52, 0.72),
    ])
    expect(rows.map((placement) => placement.row)).toEqual([0, 1, 2])
  })

  it('stacks downwards inside boxes at the top of the image', () => {
    const rows = placeLabels([detection(0.2, 0.01, 0.5, 0.5), detection(0.2, 0.02, 0.5, 0.5)])
    expect(rows).toEqual([
      { inside: true, end: false, row: 0 },
      { inside: true, end: false, row: 1 },
    ])
  })

  it('does not push a label above the image', () => {
    const rows = placeLabels([detection(0.2, 0.085, 0.5, 0.5), detection(0.2, 0.085, 0.5, 0.5)])
    expect(rows.map((placement) => placement.row)).toEqual([0, 0])
  })

  it('aligns labels of boxes on the right with the right edge', () => {
    expect(placeLabels([detection(0.7, 0.3, 0.95, 0.6)])[0]).toEqual({ inside: false, end: true, row: 0 })
  })
})
