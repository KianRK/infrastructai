// Mirrors serving/contract/analysis_response.schema.json (checked by contract.test.ts).

export type DamageClass = 'D00' | 'D10' | 'D20' | 'D40'

/** Coordinates relative to the image size (0..1), so boxes scale with the displayed image. */
export interface BoundingBox {
  x_min: number
  y_min: number
  x_max: number
  y_max: number
}

export interface Detection {
  damage_class: DamageClass
  label: string
  confidence: number
  box: BoundingBox
}

export type DescriptionSource = 'llm' | 'template' | 'no_damage'

export interface AnalysisResponse {
  detections: Detection[]
  description: string
  description_source: DescriptionSource
  image_width: number
  image_height: number
  detector_version: string
  llm_model: string
}

// Live traffic: mirrors serving/src/app/traffic/schemas.py.

export interface TrackedObject {
  /** Stable while the object stays in view. */
  id: number
  label: string
  confidence: number
  /** x_min, y_min, x_max, y_max relative to the frame size (0..1). */
  box: [number, number, number, number]
}

export interface StreamStats {
  in_view: Record<string, number>
  counted: Record<string, number>
  per_minute: number
  analysis_fps: number
  inference_ms: number
  dropped_frames: number
}

/** The analysis result of one video frame. */
export interface StreamEvent {
  stream: string
  seq: number
  /** Position of the frame in the video, in seconds. */
  t: number
  objects: TrackedObject[]
  stats: StreamStats
}

export interface StreamInfo {
  id: string
  title: string
  location: string
  attribution: string
  licence: string
  source_url: string
  duration: number
  /** Where the server's clock was in the loop when it answered. */
  position: number
  /** null for synthetic streams (dummy models). */
  video_url: string | null
  aspect_ratio: number
}

export interface StreamList {
  streams: StreamInfo[]
  classes: string[]
  /** How far behind the server's clock the video is shown, in seconds. */
  delay_seconds: number
  detector_version: string
}
