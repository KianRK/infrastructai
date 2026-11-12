import type { AnalysisResponse, DescriptionSource } from '../api/types.ts'
import { AnnotatedImage } from './AnnotatedImage.tsx'

interface Props {
  imageUrl: string
  /** null while the analysis is still running. */
  result: AnalysisResponse | null
}

const SOURCE_NOTES: Record<DescriptionSource, string> = {
  llm: 'Written by a language model from the detection results. It may contain mistakes.',
  template: 'Standard text assembled from the detection results (language model not used).',
  no_damage: 'Standard text.',
}

export function ResultView({ imageUrl, result }: Props) {
  return (
    <div className="result">
      <section className="card">
        <AnnotatedImage src={imageUrl} detections={result?.detections ?? []} />
        {result ? (
          <p className="muted">
            {result.detections.length === 0
              ? 'No damage detected.'
              : `${String(result.detections.length)} detection${result.detections.length === 1 ? '' : 's'}.`}{' '}
            Detector: {result.detector_version}
          </p>
        ) : null}
      </section>
      <section className="card" aria-live="polite">
        <h2>Assessment</h2>
        {result ? (
          <>
            {result.description.split('\n\n').map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
            <p className="muted">
              {SOURCE_NOTES[result.description_source]}
              {result.description_source === 'llm' ? ` Model: ${result.llm_model}.` : ''}
            </p>
          </>
        ) : (
          <p role="status" className="loading">
            Analysing the image… Writing the assessment can take up to half a minute.
          </p>
        )}
      </section>
    </div>
  )
}
