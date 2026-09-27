import { useState } from 'react'
import { api } from '../api/client'
import type { Lecture, Plan, Segment } from '../types'
import { CitationChips } from './CitationChips'
import { TextAreaField, TextField } from './Field'

const KIND_LABELS: Record<string, string> = {
  recap: 'Recap',
  concept: 'Concept',
  example: 'Example',
  activity: 'Activity',
  check: 'Check',
  summary: 'Summary',
}

interface Draft {
  title: string
  body: string
  minutes: number
}

export function PlanView({
  lecture,
  plan,
  onPlanChange,
}: {
  lecture: Lecture
  plan: Plan
  onPlanChange: (plan: Plan) => void
}) {
  const [editing, setEditing] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>({ title: '', body: '', minutes: 0 })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const body = plan.plan
  const fits = body.total_allocated_min === body.duration_min

  function startEdit(segment: Segment) {
    setEditing(segment.ordinal)
    setDraft({ title: segment.title, body: segment.body, minutes: segment.minutes })
  }

  async function saveEdit(ordinal: number) {
    setBusy(true)
    setError('')
    try {
      const updated = await api.editPlan(lecture.id, {
        segments: [{ ordinal, ...draft }],
      })
      onPlanChange(updated)
      setEditing(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function dropSegment(ordinal: number) {
    if (!confirm('Remove this segment? The remaining time is redistributed.')) return
    setBusy(true)
    setError('')
    try {
      onPlanChange(await api.editPlan(lecture.id, { drop_ordinals: [ordinal] }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function regenerate() {
    setBusy(true)
    setError('')
    try {
      onPlanChange(await api.generatePlan(lecture.id))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="space-y-5">
      <header className="rounded-lg border border-rule bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{body.topic}</h2>
            <p className="mt-1 text-sm text-neutral-600">{body.summary}</p>
          </div>
          <button
            onClick={() => void regenerate()}
            disabled={busy}
            className="shrink-0 rounded border border-neutral-800 px-3 py-1.5 text-xs
                       hover:bg-neutral-800 hover:text-white disabled:opacity-50"
          >
            {busy ? 'Working…' : 'Regenerate'}
          </button>
        </div>

        <dl className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-xs">
          <div>
            <dt className="text-neutral-500">Time allocated</dt>
            <dd className={fits ? 'font-medium text-emerald-700' : 'font-medium text-amber-700'}>
              {body.total_allocated_min} / {body.duration_min} min
              {fits ? ' — fits the class' : ' — does not match the class length'}
            </dd>
          </div>
          <div>
            <dt className="text-neutral-500">Grounded in your material</dt>
            <dd className="font-medium">
              {plan.grounded_segment_count} of {plan.total_segment_count} segments
            </dd>
          </div>
          <div>
            <dt className="text-neutral-500">Passages consulted</dt>
            <dd className="font-medium">{plan.retrieved_chunk_count}</dd>
          </div>
          <div>
            <dt className="text-neutral-500">Version</dt>
            <dd className="font-medium">
              v{plan.version} — {plan.model}
            </dd>
          </div>
        </dl>
      </header>

      {error && (
        <p className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">{error}</p>
      )}

      {body.clarifications_needed?.length > 0 && (
        <section className="rounded-lg border border-blue-200 bg-blue-50 p-4">
          <h3 className="text-sm font-semibold text-blue-900">
            The assistant needs clarification
          </h3>
          <p className="mt-1 text-xs text-blue-800">
            It flagged these rather than assuming an answer. Update the lecture notes and
            regenerate to resolve them.
          </p>
          <ul className="mt-2 space-y-1.5">
            {body.clarifications_needed.map((c, i) => (
              <li key={i} className="text-xs text-blue-900">
                <span className="font-medium">{c.field}:</span> {c.question}
              </li>
            ))}
          </ul>
        </section>
      )}

      {body.learning_objectives?.length > 0 && (
        <section className="rounded-lg border border-rule bg-white p-4">
          <h3 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
            Learning objectives
          </h3>
          <ul className="mt-3 space-y-3">
            {body.learning_objectives.map((o, i) => (
              <li key={i}>
                <p className="text-sm">{o.text}</p>
                <CitationChips grounding={o.grounding} citations={plan.citations} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-3">
        <h3 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
          Lecture sequence
        </h3>
        {body.segments.map((segment) => (
          <div key={segment.ordinal} className="rounded-lg border border-rule bg-white p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 text-xs text-neutral-500">
                <span className="rounded bg-neutral-100 px-1.5 py-0.5 font-medium">
                  {KIND_LABELS[segment.kind] ?? segment.kind}
                </span>
                <span>{segment.minutes} min</span>
                {segment.edited_by_professor && (
                  <span className="text-neutral-400 italic">edited by you</span>
                )}
              </div>
              <div className="flex shrink-0 gap-2 text-xs">
                <button
                  onClick={() => (editing === segment.ordinal ? setEditing(null) : startEdit(segment))}
                  className="text-neutral-500 hover:text-neutral-900"
                >
                  {editing === segment.ordinal ? 'Cancel' : 'Edit'}
                </button>
                <button
                  onClick={() => void dropSegment(segment.ordinal)}
                  className="text-neutral-400 hover:text-red-600"
                >
                  Remove
                </button>
              </div>
            </div>

            {editing === segment.ordinal ? (
              <div className="mt-3 space-y-3">
                <TextField
                  label="Segment title"
                  value={draft.title}
                  placeholder="What this part of the class covers"
                  onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                />
                <TextAreaField
                  label="What you will do in this segment"
                  rows={4}
                  value={draft.body}
                  placeholder="The explanation, worked example or activity you have in mind"
                  onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                />
                <div className="flex items-end gap-3">
                  <TextField
                    label="Minutes"
                    type="number"
                    min={0}
                    max={300}
                    className="w-28"
                    value={draft.minutes}
                    hint="Kept exactly; other segments absorb the rest."
                    onChange={(e) =>
                      setDraft({ ...draft, minutes: Number(e.target.value) })
                    }
                  />
                  <button
                    onClick={() => void saveEdit(segment.ordinal)}
                    disabled={busy}
                    className="mb-4 rounded bg-neutral-800 px-3 py-1.5 text-xs text-white
                               disabled:opacity-50"
                  >
                    Save as new version
                  </button>
                </div>
              </div>
            ) : (
              <>
                <h4 className="mt-2 font-medium">
                  {segment.ordinal}. {segment.title}
                </h4>
                <p className="mt-1 text-sm whitespace-pre-wrap text-neutral-700">{segment.body}</p>
                <CitationChips grounding={segment.grounding} citations={plan.citations} />
              </>
            )}
          </div>
        ))}
      </section>

      {body.misconceptions?.length > 0 && (
        <section className="rounded-lg border border-rule bg-white p-4">
          <h3 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
            Likely student misconceptions
          </h3>
          <ul className="mt-3 space-y-3">
            {body.misconceptions.map((m, i) => (
              <li key={i}>
                <p className="text-sm">{m.text}</p>
                <CitationChips grounding={m.grounding} citations={plan.citations} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  )
}
