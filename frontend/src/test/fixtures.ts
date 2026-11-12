import type { AnalysisResponse } from '../api/types.ts'

export const analysisWithDamage: AnalysisResponse = {
  detections: [
    {
      damage_class: 'D40',
      label: 'pothole',
      confidence: 0.91,
      box: { x_min: 0.4, y_min: 0.55, x_max: 0.62, y_max: 0.8 },
    },
    {
      damage_class: 'D00',
      label: 'longitudinal crack',
      confidence: 0.674,
      box: { x_min: 0.1, y_min: 0.02, x_max: 0.18, y_max: 0.9 },
    },
  ],
  description: 'One pothole and one longitudinal crack were found.\n\nSeverity is approximate.',
  description_source: 'llm',
  image_width: 640,
  image_height: 480,
  detector_version: 'roadscan-detector v3',
  llm_model: 'qwen2.5-1.5b-instruct-q4_k_m',
}

export const analysisWithoutDamage: AnalysisResponse = {
  ...analysisWithDamage,
  detections: [],
  description: 'No road damage was detected in this image.',
  description_source: 'no_damage',
}

export function imageFile(name = 'road.jpg', type = 'image/jpeg', bytes = 1024): File {
  return new File([new Uint8Array(bytes)], name, { type })
}
