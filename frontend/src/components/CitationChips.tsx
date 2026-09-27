import { useState } from 'react'
import type { Citation } from '../types'

interface Props {
  grounding: number[]
  citations: Record<string, Citation>
}

/**
 * Renders the citations attached to one piece of generated content.
 *
 * Clicking a chip reveals the verbatim text of the cited chunk. That is the
 * point of the whole system: the professor can confirm, without leaving the
 * page, that the cited words really are on the cited page.
 */
export function CitationChips({ grounding, citations }: Props) {
  const [open, setOpen] = useState(false)

  const resolved = grounding
    .map((id) => citations[String(id)])
    .filter((c): c is Citation => Boolean(c))

  if (resolved.length === 0) {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full border border-amber-300
                   bg-amber-50 px-2.5 py-0.5 text-xs text-amber-800"
        title="Nothing in the uploaded material supports this, so it is offered as a suggestion only."
      >
        <span aria-hidden>○</span> Model suggestion — not from your sources
      </span>
    )
  }

  // Several chunks from the same page render identically; group them so the
  // professor sees one reference with all of its supporting excerpts.
  const groups = new Map<string, Citation[]>()
  for (const citation of resolved) {
    const existing = groups.get(citation.display)
    if (existing) existing.push(citation)
    else groups.set(citation.display, [citation])
  }

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex flex-wrap items-center gap-1.5 text-left"
        aria-expanded={open}
      >
        {[...groups.entries()].map(([display, items]) => (
          <span
            key={display}
            className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300
                       bg-emerald-50 px-2.5 py-0.5 text-xs text-emerald-900
                       hover:border-emerald-500"
          >
            <span aria-hidden>✓</span>
            {display}
            {items.length > 1 && (
              <span className="text-emerald-700">×{items.length}</span>
            )}
          </span>
        ))}
        <span className="text-xs text-neutral-500 underline">
          {open ? 'hide source text' : 'show source text'}
        </span>
      </button>

      {open && (
        <div className="mt-2 space-y-2 border-l-2 border-emerald-300 pl-3">
          {resolved.map((citation) => (
            <figure key={citation.chunk_id} className="text-xs">
              <blockquote className="whitespace-pre-wrap text-neutral-700 italic">
                “{citation.snippet}”
              </blockquote>
              <figcaption className="mt-1 text-neutral-500">
                {citation.document_filename} — page {citation.page_no}
                {citation.authors && ` — ${citation.authors}`}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  )
}
