import type { CSSProperties } from 'react'

import type { Detection } from '../api/types.ts'
import { placeLabels } from '../labels.ts'

interface Props {
  src: string
  detections: Detection[]
}

function percent(fraction: number): string {
  return `${(fraction * 100).toFixed(2)}%`
}

/**
 * The image with one positioned box per detection. Box coordinates are relative
 * (0..1), so percentages keep them aligned at any display size.
 */
export function AnnotatedImage({ src, detections }: Props) {
  const placements = placeLabels(detections)
  return (
    <div className="annotated">
      <img src={src} alt="Uploaded road" />
      {detections.map((detection, index) => {
        const { box } = detection
        const { inside, end, row } = placements[index]
        const caption = `${detection.label} ${String(Math.round(detection.confidence * 100))}%`
        return (
          <div
            key={index}
            className={`box ${detection.damage_class}`}
            data-testid="detection-box"
            title={caption}
            style={{
              left: percent(box.x_min),
              top: percent(box.y_min),
              width: percent(box.x_max - box.x_min),
              height: percent(box.y_max - box.y_min),
            }}
          >
            {/* Keep labels on the image: inside the box near the top edge, right-aligned
                for boxes in the right part (matters on narrow screens), and stacked
                where boxes share a corner. */}
            <span
              className={`tag${inside ? ' inside' : ''}${end ? ' end' : ''}`}
              style={{ '--row': row } as CSSProperties}
            >
              {caption}
            </span>
          </div>
        )
      })}
    </div>
  )
}
