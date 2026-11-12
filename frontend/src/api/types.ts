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
