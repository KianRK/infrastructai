import { useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import { ACCEPTED_TYPES, validateImageFile } from '../validation.ts'

interface Props {
  disabled: boolean
  onFile: (file: File) => void
}

export function UploadPanel({ disabled, onFile }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  function accept(file: File | undefined) {
    if (!file) return
    const problem = validateImageFile(file)
    setError(problem)
    if (problem === null) onFile(file)
  }

  function onChange(event: ChangeEvent<HTMLInputElement>) {
    accept(event.target.files?.[0])
    event.target.value = '' // allow choosing the same file again
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    setDragging(false)
    if (!disabled) accept(event.dataTransfer.files[0])
  }

  return (
    <div
      className={`card upload${dragging ? ' dragging' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => {
        setDragging(false)
      }}
      onDrop={onDrop}
    >
      <p>Drop a road photo here, or</p>
      <button type="button" disabled={disabled} onClick={() => input.current?.click()}>
        Choose image
      </button>
      <input
        ref={input}
        type="file"
        accept={ACCEPTED_TYPES.join(',')}
        aria-label="Road image"
        hidden
        disabled={disabled}
        onChange={onChange}
      />
      <p className="muted">JPEG, PNG or WebP, up to 10 MB.</p>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}
