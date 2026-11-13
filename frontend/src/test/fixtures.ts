import type { AnalysisResponse, StreamEvent, StreamList } from '../api/types.ts'

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
  description: 'One pothole and one longitudinal crack were found.',
  recommendations: [
    {
      damage_class: 'D40',
      label: 'pothole',
      severity: 'moderate',
      needs_verification: false,
      usual_repair: 'Fill the hole with cold mix, then patch it durably.',
      typical_causes: 'Water entering a weakened surface.',
    },
    {
      damage_class: 'D00',
      label: 'longitudinal crack',
      severity: 'low',
      needs_verification: true,
      usual_repair: 'Clean and seal the crack.',
      typical_causes: 'Poorly bonded construction joints.',
    },
  ],
  disclaimer: 'Severity is approximate.',
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
  recommendations: [],
  disclaimer: null,
  description_source: 'no_damage',
}

export function imageFile(name = 'road.jpg', type = 'image/jpeg', bytes = 1024): File {
  return new File([new Uint8Array(bytes)], name, { type })
}

export const streamList: StreamList = {
  streams: [
    {
      id: 'junction',
      title: 'Tram junction',
      location: 'Düsseldorf, Germany',
      attribution: 'Slick, Wikimedia Commons',
      licence: 'CC0 1.0',
      source_url: 'https://commons.wikimedia.org/wiki/File:Example.ogv',
      duration: 120,
      position: 10,
      video_url: '/api/traffic/streams/junction/video',
      aspect_ratio: 1.7778,
    },
  ],
  classes: ['person', 'car', 'train'],
  delay_seconds: 1.5,
  detector_version: 'roadscan-traffic v1',
}

/** A result for the frame the page shows right after loading `streamList`. */
export function streamEvent(overrides: Partial<StreamEvent> = {}): StreamEvent {
  return {
    stream: 'junction',
    seq: 1,
    t: streamList.streams[0].position - streamList.delay_seconds,
    objects: [
      { id: 7, label: 'car', confidence: 0.9, box: [0.25, 0.5, 0.5, 0.75] },
      { id: 9, label: 'train', confidence: 0.8, box: [0.6, 0.02, 0.9, 0.4] },
    ],
    stats: {
      in_view: { car: 1, train: 1 },
      counted: { car: 12, train: 2, person: 5 },
      per_minute: 8,
      analysis_fps: 5,
      inference_ms: 31.4,
      dropped_frames: 0,
    },
    ...overrides,
  }
}
