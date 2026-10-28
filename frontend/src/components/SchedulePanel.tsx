import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { BlockedDate, Course, Lecture, RecalibrateResult } from '../types'
import { TextField } from './Field'

/**
 * Week 5: the teaching calendar and schedule re-calibration.
 *
 * The professor sets when the course meets, marks lectures delivered, then
 * records a disruption (holiday, missed class, shorter classes). Preview shows
 * the recalculated schedule; nothing changes until they press Apply.
 */

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function fmt(day: string | null): string {
  if (!day) return 'no date'
  return new Date(`${day}T00:00:00`).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
}

const button =
  'rounded bg-neutral-800 px-3 py-1.5 text-xs text-white disabled:opacity-50'
const ghost =
  'rounded border border-rule px-3 py-1.5 text-xs hover:border-neutral-400 disabled:opacity-50'

export function SchedulePanel({
  course,
  lectures,
  onChanged,
}: {
  course: Course
  lectures: Lecture[]
  onChanged: () => Promise<void>
}) {
  // Calendar
  const [startDate, setStartDate] = useState(course.start_date ?? '')
  const [endDate, setEndDate] = useState(course.end_date ?? '')
  const [days, setDays] = useState<number[]>(course.meeting_days ?? [])

  // Disruption
  const [fromDate, setFromDate] = useState('')
  const [holidayDate, setHolidayDate] = useState('')
  const [holidayReason, setHolidayReason] = useState('')
  const [holidays, setHolidays] = useState<BlockedDate[]>([])
  const [missed, setMissed] = useState<number[]>([])
  const [newDuration, setNewDuration] = useState('')

  const [result, setResult] = useState<RecalibrateResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setStartDate(course.start_date ?? '')
    setEndDate(course.end_date ?? '')
    setDays(course.meeting_days ?? [])
      // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [course.id, course.start_date, course.end_date, (course.meeting_days ?? []).join(',')])

  // Any edit makes an earlier preview stale.
  function touch() {
    setResult(null)
    setError('')
  }

  async function run<T>(work: () => Promise<T>): Promise<T | undefined> {
    setBusy(true)
    setError('')
    try {
      return await work()
    } catch (e) {
      setError((e as Error).message)
      return undefined
    } finally {
      setBusy(false)
    }
  }

  async function saveCalendar() {
    await run(async () => {
      await api.updateCourse(course.id, {
        start_date: startDate || null,
        end_date: endDate || null,
        meeting_days: days,
      })
      await onChanged()
    })
  }

  async function toggleDelivered(lecture: Lecture) {
    await run(async () => {
      await api.updateLecture(lecture.id, {
        status: lecture.status === 'delivered' ? 'planned' : 'delivered',
      })
      setMissed((m) => m.filter((s) => s !== lecture.seq_no))
      touch()
      await onChanged()
    })
  }

  function addHoliday() {
    if (!holidayDate) return
    setHolidays((h) => [
      ...h.filter((x) => x.date !== holidayDate),
      { date: holidayDate, reason: holidayReason || 'holiday' },
    ])
    setHolidayDate('')
    setHolidayReason('')
    touch()
  }

async function removeBlocked(day: string) {
    await run(async () => {
      await api.updateCourse(course.id, {
        blocked_dates: course.blocked_dates.filter((b) => b.date !== day),
      })
      touch()
      await onChanged()
    })
  }

  function body(apply: boolean) {
    return {
      apply,
      from_date: fromDate || null,
      blocked_dates: holidays,
      missed_seq_nos: missed,
      new_duration_min: newDuration ? Number(newDuration) : null,
    }
  }

  async function preview() {
    const out = await run(() => api.recalibrate(course.id, body(false)))
    if (out) setResult(out)
  }

  async function applyIt() {
    const out = await run(() => api.recalibrate(course.id, body(true)))
    if (!out) return
    setResult(out)
    setHolidays([])
    setMissed([])
    setNewDuration('')
    setFromDate('')
    await onChanged()
  }

  const calendarSet = (course.meeting_days ?? []).length > 0 && !!course.start_date
  const active = lectures.filter((l) => l.status !== 'merged')

  return (
    <details className="rounded-lg border border-rule bg-white p-4" open={!calendarSet}>
      <summary className="cursor-pointer text-sm font-semibold tracking-wide text-neutral-700 uppercase">
        Schedule &amp; re-calibration
      </summary>

      {error && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {/* 1. When the course meets */}
      <div className="mt-3 space-y-3 border-t border-rule pt-3">
        <p className="text-xs font-medium text-neutral-700">Teaching calendar</p>
        <div className="flex flex-wrap items-end gap-3">
          <TextField
            label="First class"
            type="date"
            className="w-40"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
          <TextField
            label="Last class (optional)"
            type="date"
            className="w-40"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
        <div>
          <p className="text-xs font-medium text-neutral-700">Class days</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {WEEKDAYS.map((name, i) => (
              <button
                key={name}
                type="button"
                onClick={() =>
                  setDays((d) => (d.includes(i) ? d.filter((x) => x !== i) : [...d, i].sort()))
                }
                className={`rounded border px-2 py-1 text-xs ${
                  days.includes(i)
                    ? 'border-neutral-800 bg-neutral-800 text-white'
                    : 'border-rule hover:border-neutral-400'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        </div>
        <button onClick={() => void saveCalendar()} disabled={busy} className={button}>
          Save calendar
        </button>
               {(course.blocked_dates ?? []).length > 0 && (
          <div className="text-[11px] text-neutral-500">
            <p>No-class dates (remove one, then Preview and Apply to use it again):</p>
            <ul className="mt-1 flex flex-wrap gap-1">
              {course.blocked_dates.map((b) => (
                <li
                  key={b.date}
                  className="flex items-center gap-1 rounded bg-neutral-100 px-2 py-0.5"
                >
                  {fmt(b.date)} ({b.reason})
                  <button
                    onClick={() => void removeBlocked(b.date)}
                    disabled={busy}
                    className="text-neutral-400 hover:text-red-600"
                    aria-label={`Remove ${b.date}`}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* 2. Where each lecture stands */}
      {active.length > 0 && (
        <div className="mt-4 border-t border-rule pt-3">
          <p className="text-xs font-medium text-neutral-700">Lectures</p>
          <ul className="mt-2 space-y-1">
            {active.map((l) => (
              <li key={l.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate">
                  {l.seq_no}. {l.topic}
                  <span className="ml-1 text-neutral-500">
                    — {fmt(l.scheduled_date)}, {l.duration_min}m
                  </span>
                </span>
                {l.status === 'delivered' ? (
                  <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
                    delivered
                  </span>
                ) : (
                  l.scheduled_date && (
                    <label className="flex items-center gap-1 text-[11px] text-neutral-600">
                      <input
                        type="checkbox"
                        checked={missed.includes(l.seq_no)}
                        onChange={() => {
                          setMissed((m) =>
                            m.includes(l.seq_no)
                              ? m.filter((s) => s !== l.seq_no)
                              : [...m, l.seq_no],
                          )
                          touch()
                        }}
                      />
                      missed
                    </label>
                  )
                )}
                <button
                  onClick={() => void toggleDelivered(l)}
                  disabled={busy}
                  className="text-[11px] text-neutral-500 hover:text-neutral-900"
                >
                  {l.status === 'delivered' ? 'undo' : 'mark delivered'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 3. What changed */}
      <div className="mt-4 space-y-3 border-t border-rule pt-3">
        <p className="text-xs font-medium text-neutral-700">Something changed?</p>
        <div className="flex flex-wrap items-end gap-3">
          <TextField
            label="No class on"
            type="date"
            className="w-40"
            value={holidayDate}
            onChange={(e) => setHolidayDate(e.target.value)}
          />
          <TextField
            label="Reason"
            className="w-40"
            placeholder="e.g. Diwali"
            value={holidayReason}
            onChange={(e) => setHolidayReason(e.target.value)}
          />
          <button type="button" onClick={addHoliday} className={ghost}>
            Add date
          </button>
        </div>
        {holidays.length > 0 && (
          <ul className="flex flex-wrap gap-1">
            {holidays.map((h) => (
              <li
                key={h.date}
                className="flex items-center gap-1 rounded bg-neutral-100 px-2 py-0.5 text-[11px]"
              >
                {fmt(h.date)} — {h.reason}
                <button
                  onClick={() => {
                    setHolidays((x) => x.filter((y) => y.date !== h.date))
                    touch()
                  }}
                  className="text-neutral-400 hover:text-red-600"
                  aria-label="Remove date"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap items-end gap-3">
          <TextField
            label="New class length (minutes)"
            type="number"
            min={5}
            max={300}
            className="w-44"
            placeholder={String(course.lecture_duration_min)}
            value={newDuration}
            onChange={(e) => {
              setNewDuration(e.target.value)
              touch()
            }}
          />
          <TextField
            label="Re-plan from (default today)"
            type="date"
            className="w-44"
            value={fromDate}
            onChange={(e) => {
              setFromDate(e.target.value)
              touch()
            }}
          />
        </div>
        <div className="flex gap-2">
          <button onClick={() => void preview()} disabled={busy || !calendarSet} className={ghost}>
            Preview new schedule
          </button>
          <button
            onClick={() => void applyIt()}
            disabled={busy || !result || result.applied}
            className={button}
          >
            Apply
          </button>
        </div>
        {!calendarSet && (
          <p className="text-[11px] text-neutral-500">
            Save the first class date and class days first.
          </p>
        )}
      </div>

      {/* 4. The recalculated schedule */}
      {result && (
        <div className="mt-4 border-t border-rule pt-3">
          <p className="text-xs font-medium text-neutral-700">
            {result.applied ? 'Applied' : 'Preview — nothing has changed yet'}
            {result.available_slots !== null &&
              ` · ${result.available_slots} classes left from ${fmt(result.from_date)}`}
          </p>
          <table className="mt-2 w-full text-left text-xs">
            <thead className="text-neutral-500">
              <tr>
                <th className="py-1 font-normal">Lecture</th>
                <th className="py-1 font-normal">Date</th>
                <th className="py-1 font-normal">Length</th>
              </tr>
            </thead>
            <tbody>
              {result.changes.map((c) => (
                <tr
                  key={c.lecture_ids.join('-')}
                  className={c.changed ? 'bg-amber-50' : ''}
                >
                  <td className="py-1 pr-2">
                    {c.seq_nos.join(' + ')}. {c.topic}
                    {c.merged && <span className="ml-1 text-amber-700">(merged)</span>}
                  </td>
                  <td className="py-1 pr-2 whitespace-nowrap">
                    {c.old_date !== c.new_date ? (
                      <>
                        <span className="text-neutral-400 line-through">{fmt(c.old_date)}</span>{' '}
                        {fmt(c.new_date)}
                      </>
                    ) : (
                      fmt(c.new_date)
                    )}
                  </td>
                  <td className="py-1 whitespace-nowrap">
                    {c.old_duration_min !== c.new_duration_min
                      ? `${c.old_duration_min} → ${c.new_duration_min}m`
                      : `${c.new_duration_min}m`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.warnings.length > 0 && (
            <ul className="mt-2 list-disc space-y-1 pl-4 text-[11px] text-amber-800">
              {result.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </details>
  )
}