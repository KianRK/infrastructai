import type { Detection } from './api/types.ts'

export interface LabelPlacement {
  /** Label sits inside the box (the box touches the top of the image). */
  inside: boolean
  /** Label is aligned with the right edge of the box. */
  end: boolean
  /** Number of label heights the label is moved away from the box edge. */
  row: number
}

/**
 * Assumed label size relative to the image. Labels are sized in rem, so this is an
 * estimate for typical display widths; it only decides when two labels are stacked.
 */
const LABEL_WIDTH = 0.22
const LABEL_HEIGHT = 0.045

/**
 * Where each detection's label goes. Labels start at a corner of their box; boxes of
 * different classes on the same damage share that corner, so a label that would cover
 * an earlier one moves one row further (up, or down for labels inside the box).
 */
export function placeLabels(detections: Detection[]): LabelPlacement[] {
  const placed: { x: number; y: number }[] = []
  return detections.map(({ box }) => {
    const inside = box.y_min < 0.08
    const end = box.x_min > 0.55
    const x = end ? box.x_max - LABEL_WIDTH : box.x_min
    const direction = inside ? 1 : -1
    let row = 0
    let y = inside ? box.y_min : box.y_min - LABEL_HEIGHT
    const covers = (other: { x: number; y: number }) =>
      Math.abs(other.x - x) < LABEL_WIDTH && Math.abs(other.y - y) < LABEL_HEIGHT * 0.9
    // Outside labels must stay on the image; inside labels have the whole box below.
    while (placed.some(covers) && (inside || y - LABEL_HEIGHT >= 0) && row < 6) {
      row += 1
      y += direction * LABEL_HEIGHT
    }
    placed.push({ x, y })
    return { inside, end, row }
  })
}
