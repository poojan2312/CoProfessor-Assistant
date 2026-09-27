import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Source } from '../types'
import { Field, TextField } from './Field'

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-neutral-100 text-neutral-600',
  processing: 'bg-blue-50 text-blue-700',
  ready: 'bg-emerald-50 text-emerald-800',
  failed: 'bg-red-50 text-red-700',
}

export function MaterialPanel({
  courseId,
  onReadyCountChange,
}: {
  courseId: number
  onReadyCountChange?: (count: number) => void
}) {
  const [sources, setSources] = useState<Source[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      const rows = await api.listMaterials(courseId)
      setSources(rows)
      onReadyCountChange?.(
        rows.filter((s) => s.documents.some((d) => d.ingest_status === 'ready')).length,
      )
    } catch (e) {
      setError((e as Error).message)
    }
  }, [courseId, onReadyCountChange])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Ingestion runs in the background, so poll while anything is still working.
  const stillWorking = sources.some((s) =>
    s.documents.some((d) => d.ingest_status === 'pending' || d.ingest_status === 'processing'),
  )
  useEffect(() => {
    if (!stillWorking) return
    const timer = setInterval(() => void refresh(), 2500)
    return () => clearInterval(timer)
  }, [stillWorking, refresh])

  async function upload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const file = form.get('file')
    if (!(file instanceof File) || file.size === 0) {
      setError('Choose a PDF first.')
      return
    }
    setBusy(true)
    setError('')
    try {
      await api.uploadMaterial(courseId, form)
      event.currentTarget.reset()
      if (fileInput.current) fileInput.current.value = ''
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove(sourceId: number) {
    if (!confirm('Remove this source? Anything citing it will lose its reference.')) return
    try {
      await api.deleteMaterial(sourceId)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <section className="rounded-lg border border-rule bg-white p-4">
      <h3 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
        Course material
      </h3>
      <p className="mt-1 text-xs text-neutral-500">
        The assistant may only cite what you upload here. Nothing else is treated as a source.
      </p>

      <form onSubmit={upload} className="mt-3 space-y-3">
        <Field
          label="Course material (PDF)"
          hint="Slides, notes or a textbook chapter. Scanned PDFs need OCR first."
        >
          {(id) => (
            <input
              id={id}
              ref={fileInput}
              type="file"
              name="file"
              accept="application/pdf,.pdf"
              className="block w-full text-xs file:mr-3 file:rounded file:border-0
                         file:bg-neutral-800 file:px-3 file:py-1.5 file:text-white"
            />
          )}
        </Field>
        <TextField
          label="Source title"
          name="title"
          placeholder="e.g. Operating System Concepts"
          hint="Shown in citations. Defaults to the file name."
        />
        <TextField
          label="Author(s)"
          name="authors"
          placeholder="e.g. Silberschatz, Galvin, Gagne"
          hint="Optional. Also shown in citations."
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-neutral-800 px-3 py-1.5 text-xs text-white disabled:opacity-50"
        >
          {busy ? 'Uploading…' : 'Upload PDF'}
        </button>
      </form>

      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

      <ul className="mt-4 space-y-2">
        {sources.length === 0 && (
          <li className="text-xs text-neutral-400">No material uploaded yet.</li>
        )}
        {sources.map((source) => {
          const doc = source.documents[0]
          const status = doc?.ingest_status ?? 'pending'
          return (
            <li
              key={source.id}
              className="flex items-start justify-between gap-2 rounded border border-rule p-2"
            >
              <div className="min-w-0">
                <p className="truncate text-xs font-medium">{source.title}</p>
                <p className="mt-0.5 text-[11px] text-neutral-500">
                  {doc?.filename}
                  {status === 'ready' && ` — ${doc.page_count} pages, ${doc.chunk_count} passages`}
                </p>
                {status === 'failed' && (
                  <p className="mt-1 text-[11px] text-red-600">{doc.ingest_error}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] ${STATUS_STYLES[status] ?? ''}`}
                >
                  {status === 'ready' ? 'indexed' : status}
                </span>
                <button
                  onClick={() => void remove(source.id)}
                  className="text-[11px] text-neutral-400 hover:text-red-600"
                  aria-label={`Remove ${source.title}`}
                >
                  ✕
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
