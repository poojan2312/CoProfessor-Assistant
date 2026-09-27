import { useEffect, useState } from 'react'
import { ApiError, teachingSupportApi } from '../api/client'
import type { Lecture, TeachingSupport } from '../types'
import { CitationChips } from './CitationChips'

const FORMAT_LABELS: Record<string, string> = {
  pair: 'Pair work',
  group: 'Group work',
  demo: 'Live demo',
  poll: 'Quick poll',
  debate: 'Debate',
  think_pair_share: 'Think–pair–share',
}

function Section({ title, blurb, children }: {
  title: string
  blurb: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-lg border border-rule bg-white p-4">
      <h3 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
        {title}
      </h3>
      <p className="mt-0.5 text-[11px] text-neutral-500">{blurb}</p>
      <div className="mt-3 space-y-4">{children}</div>
    </section>
  )
}

export function TeachingSupportPanel({
  lecture,
  refreshKey,
}: {
  lecture: Lecture
  refreshKey: number
}) {
  const [support, setSupport] = useState<TeachingSupport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setSupport(null)
    setError('')
    teachingSupportApi
      .get(lecture.id)
      .then(setSupport)
      .catch((e) => {
        if (!(e instanceof ApiError && e.status === 404)) setError((e as Error).message)
      })
  }, [lecture.id, refreshKey])

  async function generate() {
    setBusy(true)
    setError('')
    try {
      setSupport(await teachingSupportApi.generate(lecture.id))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!support) {
    return (
      <div className="rounded-lg border border-dashed border-rule p-8 text-center">
        <p className="text-sm text-neutral-600">
          No teaching support yet for “{lecture.topic}”.
        </p>
        <p className="mx-auto mt-1 max-w-md text-xs text-neutral-500">
          Real-world and industry applications, classroom activities, interactive ways
          to present the topic, and alternative explanations for the ideas students
          find hardest.
        </p>
        <button
          onClick={() => void generate()}
          disabled={busy}
          className="mt-3 rounded bg-neutral-800 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {busy ? 'Generating…' : 'Generate teaching support'}
        </button>
        {error && <p className="mt-3 text-xs text-red-600">{error}</p>}
      </div>
    )
  }

  const body = support.support
  const cites = support.citations

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between rounded-lg border border-rule bg-white px-4 py-2">
        <p className="text-[11px] text-neutral-500">
          v{support.version} · {support.retrieved_chunk_count} passages consulted
        </p>
        <button
          onClick={() => void generate()}
          disabled={busy}
          className="rounded border border-neutral-800 px-3 py-1 text-xs
                     hover:bg-neutral-800 hover:text-white disabled:opacity-50"
        >
          {busy ? 'Working…' : 'Regenerate'}
        </button>
      </div>

      {error && (
        <p className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">
          {error}
        </p>
      )}

      {body.industry_applications?.length > 0 && (
        <Section
          title="Real-world and industry applications"
          blurb="Where this topic shows up in professional work. Your textbook rarely covers current practice, so most of these are honestly uncited."
        >
          {body.industry_applications.map((item, i) => (
            <div key={i}>
              <h4 className="text-sm font-medium">{item.title}</h4>
              <p className="mt-0.5 text-sm text-neutral-700">{item.text}</p>
              <CitationChips grounding={item.grounding} citations={cites} />
            </div>
          ))}
        </Section>
      )}

      {body.activities?.length > 0 && (
        <Section title="Classroom activities" blurb="Runnable in the class time you have.">
          {body.activities.map((item, i) => (
            <div key={i}>
              <div className="flex flex-wrap items-center gap-2">
                <h4 className="text-sm font-medium">{item.title}</h4>
                <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] text-neutral-600">
                  {FORMAT_LABELS[item.format] ?? item.format}
                </span>
                <span className="text-[11px] text-neutral-500">{item.minutes} min</span>
              </div>
              <p className="mt-0.5 text-sm whitespace-pre-wrap text-neutral-700">
                {item.instructions}
              </p>
              <CitationChips grounding={item.grounding} citations={cites} />
            </div>
          ))}
        </Section>
      )}

      {body.interactive_techniques?.length > 0 && (
        <Section
          title="Interactive ways to present this"
          blurb="Alternatives to talking at the room."
        >
          {body.interactive_techniques.map((item, i) => (
            <div key={i}>
              <p className="text-sm text-neutral-700">{item.text}</p>
              <CitationChips grounding={item.grounding} citations={cites} />
            </div>
          ))}
        </Section>
      )}

      {body.alt_explanations?.length > 0 && (
        <Section
          title="Another way to explain it"
          blurb="For the ideas students get stuck on."
        >
          {body.alt_explanations.map((item, i) => (
            <div key={i}>
              <h4 className="text-sm font-medium">{item.concept}</h4>
              <p className="mt-0.5 text-sm text-neutral-700">{item.explanation}</p>
              {item.analogy && (
                <p className="mt-1 border-l-2 border-rule pl-3 text-sm text-neutral-600 italic">
                  {item.analogy}
                </p>
              )}
              <CitationChips grounding={item.grounding} citations={cites} />
            </div>
          ))}
        </Section>
      )}
    </div>
  )
}
