import { useEffect, useRef, useState } from 'react'
import { chatApi } from '../api/client'
import type { ChatMessage, ChatTurn, Citation, Lecture } from '../types'
import { CitationChips } from './CitationChips'

interface Props {
  courseId: number
  lecture: Lecture | null
  /** Called after a turn so the parent can refetch whatever changed. */
  onTurn: (turn: ChatTurn) => void
}

const SUGGESTIONS = [
  'What does my material say about this topic?',
  'Make this lecture 90 minutes',
  'Suggest a classroom activity',
  'Which segment is weakest?',
]

export function ChatPanel({ courseId, lecture, onTurn }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [citations, setCitations] = useState<Record<string, Citation>>({})
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMessages([])
    setCitations({})
    setError('')
    Promise.all([chatApi.history(courseId), chatApi.citations(courseId)])
      .then(([history, cites]) => {
        setMessages(history)
        setCitations(cites)
      })
      .catch((e) => setError((e as Error).message))
  }, [courseId])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  async function send(text: string) {
    const message = text.trim()
    if (!message || busy) return

    setBusy(true)
    setError('')
    // Show the professor's message straight away rather than after the round trip.
    const pending: ChatMessage = {
      id: -Date.now(),
      role: 'professor',
      content: message,
      lecture_id: lecture?.id ?? null,
      citations: [],
      action: null,
      clarification: '',
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, pending])
    setDraft('')

    try {
      const turn = await chatApi.send(courseId, message, lecture?.id ?? null)
      setMessages((prev) => [...prev, turn.message])
      setCitations((prev) => ({ ...prev, ...turn.citations }))
      onTurn(turn)
    } catch (e) {
      // Drop the optimistic message so the thread matches what the server stored.
      setMessages((prev) => prev.filter((m) => m.id !== pending.id))
      setDraft(message)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function clear() {
    if (!confirm('Clear this conversation? The lecture plans are not affected.')) return
    await chatApi.clear(courseId)
    setMessages([])
    setCitations({})
  }

  return (
    <section className="flex min-h-0 flex-col rounded-lg border border-rule bg-white">
      <header className="flex items-center justify-between border-b border-rule px-4 py-2">
        <div>
          <h2 className="text-sm font-semibold">Assistant</h2>
          <p className="text-[11px] text-neutral-500">
            {lecture
              ? `Working on lecture ${lecture.seq_no}: ${lecture.topic}`
              : 'No lecture open — say which one, or ask about the course'}
          </p>
        </div>
        {messages.length > 0 && (
          <button
            onClick={() => void clear()}
            className="text-[11px] text-neutral-400 hover:text-neutral-800"
          >
            Clear
          </button>
        )}
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {messages.length === 0 && (
          <div className="space-y-2 pt-4">
            <p className="text-xs text-neutral-500">
              Ask about your uploaded material, or just tell the assistant what to
              change. It answers from your sources and says when something is not in
              them.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => void send(s)}
                  className="rounded-full border border-rule px-2.5 py-1 text-[11px]
                             text-neutral-600 hover:border-neutral-400"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) =>
          m.role === 'professor' ? (
            <div key={m.id} className="flex justify-end">
              <p
                className="max-w-[85%] rounded-lg rounded-br-sm bg-neutral-800 px-3 py-2
                           text-xs whitespace-pre-wrap text-white"
              >
                {m.content}
              </p>
            </div>
          ) : (
            <div key={m.id} className="max-w-[92%] space-y-1.5">
              <p className="text-xs whitespace-pre-wrap text-neutral-800">{m.content}</p>

              {m.clarification && (
                <p className="rounded border border-blue-200 bg-blue-50 px-2.5 py-1.5
                              text-xs text-blue-900">
                  {m.clarification}
                </p>
              )}

              {m.action?.summary && (
                <p className="text-[11px] text-emerald-700">✎ {m.action.summary}</p>
              )}
              {m.action?.refused && (
                <p className="text-[11px] text-amber-700">
                  Nothing was changed — {m.action.refused}.
                </p>
              )}

              {m.citations.length > 0 && (
                <CitationChips grounding={m.citations} citations={citations} />
              )}
            </div>
          ),
        )}

        {busy && <p className="text-xs text-neutral-400">Thinking…</p>}
        <div ref={endRef} />
      </div>

      {error && (
        <p className="mx-4 mb-2 rounded border border-red-200 bg-red-50 px-2.5 py-1.5
                      text-[11px] text-red-700">
          {error}
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void send(draft)
        }}
        className="border-t border-rule p-3"
      >
        <label htmlFor="chat-input" className="sr-only">
          Message the assistant
        </label>
        <div className="flex gap-2">
          <textarea
            id="chat-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send(draft)
              }
            }}
            rows={2}
            placeholder="Ask a question, or say what to change. Enter to send, Shift+Enter for a new line."
            className="flex-1 resize-none rounded border border-rule px-2 py-1.5 text-xs
                       focus:border-neutral-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy || !draft.trim()}
            className="self-end rounded bg-neutral-800 px-3 py-1.5 text-xs text-white
                       disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </form>
    </section>
  )
}
