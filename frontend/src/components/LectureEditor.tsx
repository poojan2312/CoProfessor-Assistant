import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Lecture } from '../types'
import { TextAreaField, TextField } from './Field'

/**
 * Editing an existing lecture.
 *
 * Closes the Week 2 gap where `PATCH /api/lectures/{id}` existed but the UI could
 * only ever create a lecture — topic, duration and notes were write-once from the
 * browser.
 */
export function LectureEditor({
  lecture,
  onSaved,
  onDeleted,
}: {
  lecture: Lecture
  onSaved: (lecture: Lecture) => void
  onDeleted: () => void
}) {
  const [form, setForm] = useState({
    topic: lecture.topic,
    duration_min: lecture.duration_min,
    scheduled_date: lecture.scheduled_date ?? '',
    student_level_override: lecture.student_level_override,
    notes: lecture.notes,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setForm({
      topic: lecture.topic,
      duration_min: lecture.duration_min,
      scheduled_date: lecture.scheduled_date ?? '',
      student_level_override: lecture.student_level_override,
      notes: lecture.notes,
    })
    setSaved(false)
    setError('')
  }, [lecture])

  const dirty =
    form.topic !== lecture.topic ||
    form.duration_min !== lecture.duration_min ||
    (form.scheduled_date || null) !== lecture.scheduled_date ||
    form.student_level_override !== lecture.student_level_override ||
    form.notes !== lecture.notes

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const updated = await api.updateLecture(lecture.id, {
        ...form,
        scheduled_date: form.scheduled_date || null,
      })
      onSaved(updated)
      setSaved(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!confirm(`Delete lecture ${lecture.seq_no}? Its plans go with it.`)) return
    await api.deleteLecture(lecture.id)
    onDeleted()
  }

  return (
    <form onSubmit={save} className="space-y-3 rounded-lg border border-rule bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
          Lecture {lecture.seq_no} details
        </h3>
        <button
          type="button"
          onClick={() => void remove()}
          className="text-[11px] text-neutral-400 hover:text-red-600"
        >
          Delete lecture
        </button>
      </div>

      <TextField
        label="Lecture topic"
        required
        value={form.topic}
        placeholder="e.g. CPU scheduling"
        onChange={(e) => setForm({ ...form, topic: e.target.value })}
      />

      <div className="grid grid-cols-2 gap-3">
        <TextField
          label="This lecture's length (minutes)"
          type="number"
          min={5}
          max={300}
          value={form.duration_min}
          placeholder="50"
          hint="The plan is re-balanced to fit."
          onChange={(e) => setForm({ ...form, duration_min: Number(e.target.value) })}
        />
        <TextField
          label="Scheduled date"
          type="date"
          value={form.scheduled_date}
          hint="Optional."
          onChange={(e) => setForm({ ...form, scheduled_date: e.target.value })}
        />
      </div>

      <TextField
        label="Student level for this lecture"
        value={form.student_level_override}
        placeholder="e.g. 3rd year B.Tech"
        hint="Leave blank to use the course-wide level."
        onChange={(e) => setForm({ ...form, student_level_override: e.target.value })}
      />

      <TextAreaField
        label="Notes for the assistant"
        rows={3}
        value={form.notes}
        placeholder="What students have already seen, constraints, anything to avoid"
        onChange={(e) => setForm({ ...form, notes: e.target.value })}
      />

      {error && <p className="text-xs text-red-600">{error}</p>}

      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={busy || !dirty}
          className="rounded bg-neutral-800 px-3 py-1.5 text-xs text-white disabled:opacity-40"
        >
          {busy ? 'Saving…' : 'Save changes'}
        </button>
        {saved && !dirty && <span className="text-[11px] text-emerald-700">Saved.</span>}
      </div>
    </form>
  )
}
