import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from './api/client'
import { ChatPanel } from './components/ChatPanel'
import { TextAreaField, TextField } from './components/Field'
import { LectureEditor } from './components/LectureEditor'
import { MaterialPanel } from './components/MaterialPanel'
import { PlanView } from './components/PlanView'
import { TeachingSupportPanel } from './components/TeachingSupportPanel'
import type { ChatTurn, Course, Lecture, Plan } from './types'
import { SchedulePanel } from './components/SchedulePanel'

type Tab = 'plan' | 'support' | 'details'

const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: 'Lecture plan' },
  { id: 'support', label: 'Teaching support' },
  { id: 'details', label: 'Lecture details' },
]

export default function App() {
  const [courses, setCourses] = useState<Course[]>([])
  const [courseId, setCourseId] = useState<number | null>(null)
  const [lectures, setLectures] = useState<Lecture[]>([])
  const [lectureId, setLectureId] = useState<number | null>(null)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [tab, setTab] = useState<Tab>('plan')
  const [supportKey, setSupportKey] = useState(0)
  const [materialRefresh, setMaterialRefresh] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const course = courses.find((c) => c.id === courseId) ?? null
  const lecture = lectures.find((l) => l.id === lectureId) ?? null

  useEffect(() => {
    api.listCourses().then(setCourses).catch((e) => setError(e.message))
  }, [])

  const loadLectures = useCallback(async (id: number) => {
    const rows = await api.listLectures(id)
    setLectures(rows)
    return rows
  }, [])

  const loadPlan = useCallback(async (id: number) => {
    try {
      setPlan(await api.getPlan(id))
    } catch (e) {
      // A lecture with no plan yet is the normal case, not an error.
      if (e instanceof ApiError && e.status === 404) setPlan(null)
      else setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    if (courseId === null) return
    setLectureId(null)
    setPlan(null)
    void loadLectures(courseId).catch((e) => setError(e.message))
  }, [courseId, loadLectures])

  useEffect(() => {
    if (lectureId === null) {
      setPlan(null)
      return
    }
    void loadPlan(lectureId)
  }, [lectureId, loadPlan])

  /** Refetch whatever the assistant just changed. */
  async function handleTurn(turn: ChatTurn) {
    if (turn.focus_lecture_id && turn.focus_lecture_id !== lectureId) {
      setLectureId(turn.focus_lecture_id)
    }
    if (turn.course_changed) {
      setCourses(await api.listCourses())
      setMaterialRefresh((n) => n + 1)
    }
    if (turn.lecture_changed && courseId !== null) await loadLectures(courseId)
    if (turn.plan_changed) {
      const target = turn.focus_lecture_id ?? lectureId
      if (target) await loadPlan(target)
      setTab('plan')
    }
    if (turn.support_changed) {
      setSupportKey((k) => k + 1)
      setTab('support')
    }
  }

  async function createCourse(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try {
      const created = await api.createCourse({
        title: String(form.get('title') || ''),
        code: String(form.get('code') || ''),
        objectives: String(form.get('objectives') || ''),
        student_level: String(form.get('student_level') || ''),
        lecture_duration_min: Number(form.get('lecture_duration_min') || 50),
      })
      setCourses((prev) => [created, ...prev])
      setCourseId(created.id)
      event.currentTarget.reset()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function createLecture(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (courseId === null) return
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError('')
    try {
      const created = await api.createLecture(courseId, {
        topic: String(form.get('topic') || ''),
        duration_min: Number(form.get('duration_min') || course?.lecture_duration_min || 50),
      })
      await loadLectures(courseId)
      setLectureId(created.id)
      event.currentTarget.reset()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function generatePlan() {
    if (lectureId === null) return
    setBusy(true)
    setError('')
    try {
      setPlan(await api.generatePlan(lectureId))
      if (courseId !== null) await loadLectures(courseId)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-screen flex-col lg:flex-row lg:overflow-hidden">
      {/* Sidebar: course context and the sources the assistant may cite */}
      <aside className="w-full shrink-0 space-y-4 overflow-y-auto border-b border-rule
                        p-4 lg:w-72 lg:border-r lg:border-b-0">
        <div>
          <h1 className="text-base font-semibold">Co-Professor</h1>
          <p className="text-[11px] text-neutral-500">
            Lecture preparation grounded in your own material.
          </p>
        </div>

        <section className="rounded-lg border border-rule bg-white p-4">
          <h2 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
            Courses
          </h2>
          <ul className="mt-2 space-y-1">
            {courses.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => setCourseId(c.id)}
                  className={`w-full rounded px-2 py-1 text-left text-sm ${
                    c.id === courseId ? 'bg-neutral-800 text-white' : 'hover:bg-neutral-100'
                  }`}
                >
                  {c.title}
                  {c.code && <span className="ml-1 opacity-60">({c.code})</span>}
                </button>
              </li>
            ))}
            {courses.length === 0 && (
              <li className="text-xs text-neutral-400">No courses yet.</li>
            )}
          </ul>

          <details className="mt-3 border-t border-rule pt-3">
            <summary className="cursor-pointer text-xs text-neutral-600">
              Add a course
            </summary>
            <form onSubmit={createCourse} className="mt-3 space-y-3">
              <TextField
                label="Course title"
                name="title"
                required
                placeholder="e.g. Operating Systems"
              />
              <TextField label="Course code" name="code" placeholder="e.g. CS301" />
              <TextField
                label="Default lecture length (minutes)"
                name="lecture_duration_min"
                type="number"
                min={5}
                max={300}
                defaultValue={50}
                placeholder="50"
                hint="Used for new lectures; each one can differ."
              />
              <TextField
                label="Student level"
                name="student_level"
                placeholder="e.g. 3rd year B.Tech"
                hint="Sets the depth the assistant pitches at."
              />
              <TextAreaField
                label="Course objectives"
                name="objectives"
                rows={3}
                placeholder="What students should be able to do by the end"
              />
              <button
                disabled={busy}
                className="w-full rounded bg-neutral-800 px-3 py-1.5 text-xs text-white
                           disabled:opacity-50"
              >
                Add course
              </button>
            </form>
          </details>
        </section>

        {courseId !== null && <MaterialPanel courseId={courseId} refreshTrigger={materialRefresh} />}
      </aside>

      {course === null ? (
        <main className="flex flex-1 items-center justify-center p-8">
          <p className="text-sm text-neutral-500">
            Select or create a course to begin.
          </p>
        </main>
      ) : (
        <>
          {/* Chat */}
          <div className="flex min-h-[28rem] w-full shrink-0 flex-col border-b border-rule
                          p-4 lg:h-screen lg:w-[24rem] lg:border-r lg:border-b-0">
            <ChatPanel courseId={course.id} lecture={lecture} onTurn={handleTurn} />
          </div>

          {/* The plan, changing as the conversation goes */}
          <main className="min-w-0 flex-1 space-y-4 overflow-y-auto p-4">
            {error && (
              <p className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-700">
                {error}
              </p>
            )}

            <section className="rounded-lg border border-rule bg-white p-4">
              <h2 className="text-sm font-semibold tracking-wide text-neutral-700 uppercase">
                Lectures — {course.title}
              </h2>
              <div className="mt-2 flex flex-wrap gap-2">
                {lectures.map((l) => (
                  <button
                    key={l.id}
                    onClick={() => setLectureId(l.id)}
                    className={`rounded border px-3 py-1.5 text-xs ${
                      l.id === lectureId
                        ? 'border-neutral-800 bg-neutral-800 text-white'
                        : 'border-rule hover:border-neutral-400'
                    }`}
                  >
                    {l.seq_no}. {l.topic}
                    <span className="ml-1 opacity-60">{l.duration_min}m</span>
                    {l.scheduled_date && (
                      <span className="ml-1 opacity-60">· {l.scheduled_date.slice(5)}</span>
                    )}
                    {l.status !== 'planned' && (
                      <span className="ml-1 opacity-60">({l.status})</span>
                    )}
                    {l.has_plan && <span className="ml-1">•</span>}
                  </button>
                ))}
                {lectures.length === 0 && (
                  <p className="text-xs text-neutral-400">
                    No lectures yet — add one below, or ask the assistant.
                  </p>
                )}
              </div>

              <form
                onSubmit={createLecture}
                className="mt-3 flex flex-wrap items-end gap-3 border-t border-rule pt-3"
              >
                <TextField
                  label="New lecture topic"
                  name="topic"
                  required
                  className="min-w-56 flex-1"
                  placeholder="e.g. CPU scheduling"
                />
                <TextField
                  label="Length (minutes)"
                  name="duration_min"
                  type="number"
                  min={5}
                  max={300}
                  className="w-32"
                  defaultValue={course.lecture_duration_min}
                  placeholder="50"
                />
                <button
                  disabled={busy}
                  className="rounded bg-neutral-800 px-3 py-1.5 text-xs text-white
                             disabled:opacity-50"
                >
                  Add lecture
                </button>
              </form>
            </section>
              <SchedulePanel
              course={course}
              lectures={lectures}
              onChanged={async () => {
                setCourses(await api.listCourses())
                if (courseId !== null) await loadLectures(courseId)
                if (lectureId !== null) await loadPlan(lectureId)
              }}
            />
            {lecture && (
              <>
                <nav className="flex gap-1 border-b border-rule">
                  {TABS.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => setTab(t.id)}
                      className={`-mb-px border-b-2 px-3 py-1.5 text-xs ${
                        tab === t.id
                          ? 'border-neutral-800 font-medium text-neutral-900'
                          : 'border-transparent text-neutral-500 hover:text-neutral-800'
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </nav>

                {tab === 'plan' &&
                  (plan ? (
                    <PlanView lecture={lecture} plan={plan} onPlanChange={setPlan} />
                  ) : (
                    <div className="rounded-lg border border-dashed border-rule p-8 text-center">
                      <p className="text-sm text-neutral-600">
                        No plan yet for “{lecture.topic}”.
                      </p>
                      <button
                        onClick={() => void generatePlan()}
                        disabled={busy}
                        className="mt-3 rounded bg-neutral-800 px-4 py-2 text-sm text-white
                                   disabled:opacity-50"
                      >
                        {busy ? 'Generating…' : 'Generate lecture plan'}
                      </button>
                    </div>
                  ))}

                {tab === 'support' && (
                  <TeachingSupportPanel lecture={lecture} refreshKey={supportKey} />
                )}

                {tab === 'details' && (
                  <LectureEditor
                    lecture={lecture}
                    onSaved={async (updated) => {
                      if (courseId !== null) await loadLectures(courseId)
                      await loadPlan(updated.id)
                    }}
                    onDeleted={async () => {
                      setLectureId(null)
                      if (courseId !== null) await loadLectures(courseId)
                    }}
                  />
                )}
              </>
            )}
          </main>
        </>
      )}
    </div>
  )
}
