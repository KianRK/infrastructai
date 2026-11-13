import type { AnalysisResponse, DescriptionSource } from '../api/types.ts'
import { AnnotatedImage } from './AnnotatedImage.tsx'

interface Props {
  imageUrl: string
  /** null while the analysis is still running. */
  result: AnalysisResponse | null
}

const SOURCE_NOTES: Record<DescriptionSource, string> = {
  llm: 'Summary written by a language model from the detection results; it may contain mistakes. Repairs and causes are reference texts.',
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
            <p>{result.description}</p>
            {result.recommendations.length > 0 ? (
              <>
                <h3>Recommended actions</h3>
                <ul className="actions">
                  {result.recommendations.map((item) => (
                    <li key={item.damage_class} className={item.damage_class}>
                      <p className="action-head">
                        <strong>{item.label}</strong>
                        <span className={`badge ${item.severity}`}>{item.severity} severity</span>
                        {item.needs_verification ? (
                          <span className="badge verify">verify on site</span>
                        ) : null}
                      </p>
                      {item.needs_verification ? (
                        <p>The detector is unsure here: check on site before planning a repair.</p>
                      ) : null}
                      <p>{item.usual_repair}</p>
                      <details>
                        <summary>Typical causes</summary>
                        <p>{item.typical_causes}</p>
                      </details>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            {result.disclaimer ? <p className="muted">{result.disclaimer}</p> : null}
            <p className="muted">
              {SOURCE_NOTES[result.description_source]}
              {result.description_source === 'llm' ? ` Model: ${result.llm_model}.` : ''}
            </p>
          </>
        ) : (
          <p role="status" className="loading">
            Analysing the image… This can take up to half a minute.
          </p>
        )}
      </section>
    </div>
  )
}
