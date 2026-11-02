# Co-Professor AI Assistant — Phase 1

An AI co-professor that helps a professor prepare a lecture: a chat interface, structured
plans, concept sequencing, time allocation, teaching support and likely misconceptions —
all grounded in the professor's own uploaded material.

| Step | What happens | Why it matters |
|---|---|---|
| Ingest | PyMuPDF records each passage with the page it came from. Passages never span a page boundary. | `page_no` is exact, not approximate |
| Retrieve | Vector search filtered to sources the professor **approved** | "Confine to limited sources", enforced in the query, not the prompt |
| Generate | Model receives passages labelled `[S1]…[Sk]` and cites by tag only | It cannot cite what it was not given |
| Enforce | A pure function rejects any tag outside the window; one corrective retry, then the item is downgraded to ungrounded | A fabricated citation never reaches the database |
| Render | The citation string is built from database metadata | The professor sees p. 214 because the parser said so |
| Display | Clicking a citation shows the verbatim passage | The claim can be checked without leaving the page |

Content the material does not support is shown as **"Model suggestion — not from your
sources"** rather than being quietly presented as cited.

Enforcement is structural rather than a list of known fields: *any* object carrying a
`grounding` list is checked, wherever it appears in a response. So lecture plans, chat
replies and teaching support are all covered by the same thirty lines, and a citable field
added later cannot bypass the audit by being forgotten in a registry.

Time allocation is deterministic for the same reason: the model emits a relative *weight*,
and the backend apportions whole minutes that sum to exactly the class length.

## Running it

Requires Python 3.10+ and Node 18+. A `GEMINI_API_KEY` must be in `.env` at the repo root.

One-time setup:

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm install
```

Then run the two servers in **separate terminals**. In Windows `cmd` or PowerShell:

```
:: backend - http://127.0.0.1:8000  (interactive API docs at /docs)
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

```
:: frontend - http://localhost:5173
cd frontend
npm run dev
```

In Git Bash or WSL, use forward slashes instead: `../.venv/Scripts/python.exe -m uvicorn
app.main:app --reload`. Plain `..` with forward slashes is a `cmd` syntax error, which is
the most likely reason the backend command fails to start.

Activating the virtualenv first (`.venv\Scripts\activate`) lets you drop the long path and
just run `uvicorn app.main:app --reload`.

Then: create a course → upload a PDF → wait for `indexed` → add a lecture → **Generate
lecture plan**. After that, talk to it: the chat sits beside the plan and can answer from
your material or change the plan directly ("make this 90 minutes", "drop segment 4").

### Chat

One model call per turn returns the reply, its citations, and an action. The backend then
re-validates that action through the same Pydantic schemas the REST API uses and runs it
through the same service functions, so **chat can do nothing the buttons could not do** —
an instruction with invalid arguments is refused with an explanation rather than partly
applied. It is not an agentic tool loop: the free tier allows five generations per minute,
and a loop would spend that on one exchange.

Changes apply immediately and the assistant says what it did. That is safe because plans are
versioned: every edit writes a new version and nothing is overwritten. When an instruction is
genuinely ambiguous the assistant asks instead of guessing, and changes nothing that turn.

## Tests

```
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

132 tests, no network and no API key required — the model is stubbed throughout, because
what has to be trustworthy is what the system does with model output, whatever the model
returns on a given day. Each test file maps to an outcome agreed in the Phase 1 document:

| File | Verifies |
|---|---|
| `test_ingest.py` | Every passage's text really is on the page it claims, checked against the actual PDFs |
| `test_citations.py` | Rendered page numbers come from the database; model output cannot influence them |
| `test_grounding.py` | Invented tags and model-written page references are rejected |
| `test_planner.py` | Fabrication triggers a retry then degrades to ungrounded; plans fit the class |
| `test_timealloc.py` | Allocation sums to exactly the duration at any length |
| `test_llm.py` | Retry/backoff policy, quota handling, and that the API key travels in a header |
| `test_chat.py` | Instructions execute; invalid ones are refused not half-applied; fabricated citations are stripped; ambiguity asks back; history is replayed |
| `test_plan_edits.py` | The shared edit path: pinned minutes, renumbering, version semantics |
| `test_teaching_support.py` | Week 3 content is grounded and its activity formats are a closed set |

## Stack

React + TypeScript + Tailwind · FastAPI · SQLAlchemy on SQLite · ChromaDB · Gemini
`gemini-3.8-flash` and `gemini-embedding-2`.

**On the database.** The Phase 1 document specifies PostgreSQL. The code uses SQLAlchemy
against SQLite so the project runs with zero setup; moving to PostgreSQL is a change to
`database_url` in `backend/app/config.py` and nothing else.

**On the model.** Model ids were checked against the live API rather than taken from docs:
on this key `gemini-2.5-flash` returns 404, and the `google_search` grounding tool returns
429. Neither is used. External resource verification (Phase 1, Week 4) is therefore designed
around keyless public catalogues — Crossref, OpenAlex, Open Library and YouTube oEmbed —
all confirmed reachable. These are a stronger answer to the professor's question than a
search tool anyway: a catalogue lookup either resolves or it does not, and YouTube oEmbed
returns a video's *real* title for a valid id and an error for a fake one, so a claimed
title can be checked rather than trusted.

## Known limits

- **Scanned PDFs are rejected.** Text is extracted, not OCR'd; a scan reports a clear
  ingest error rather than indexing nothing.
- Uploads are PDF only.

