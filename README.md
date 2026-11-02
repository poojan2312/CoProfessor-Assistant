# Co-Professor AI Assistant — Phase 1

An AI co-professor that helps a professor prepare and adapt lectures. The professor chats with the
assistant beside a live lecture plan: it answers from the professor's own uploaded material, builds
structured plans with exact time allocation, suggests teaching support, recommends external
resources that are checked against public catalogues, and re-calibrates the schedule when classes
are missed, cancelled or shortened.

Phase 1 covers course and lecture preparation support. Final-year B.Tech project, MNNIT.

## The design commitment

The project exists because of one recurring complaint from the supervising professor: generated
content was not correctly referenced — wrong sections, wrong page numbers, wrong videos, and
"valid but wrong" references. So the system is built on a single rule:

> **The language model is never the source of a citation fact.**

Page numbers, titles and authors come from the PDF parser and the database. The model sees
passages labelled `[S1]…[Sk]` with no bibliographic detail and may only cite by tag, so it cannot
write a wrong page number.

| Step | What happens | Why it matters |
|---|---|---|
| Ingest | PyMuPDF records each passage with the PDF page it came from. Passages never span a page boundary. | `page_no` is exact, not approximate |
| Retrieve | Vector search is filtered to sources the professor **approved** | "Confine to limited sources" is enforced in the query, not the prompt |
| Generate | The model receives passages labelled `[S1]…[Sk]` and cites by tag only | It cannot cite what it was not given |
| Enforce | A pure function rejects any tag outside the retrieved window. Lecture plans get one corrective retry, then the item is downgraded to ungrounded | A fabricated citation never reaches the database |
| Render | The citation string is built from database metadata only | The professor sees "p. 214" because the parser said so |
| Display | Clicking a citation chip shows the verbatim passage and its page | The claim can be checked without leaving the page |

Content the material does not support is shown as **"Model suggestion — not from your sources"**
rather than being presented as cited.

Enforcement is structural: *any* object carrying a `grounding` list is checked wherever it appears
in a response, so lecture plans, chat replies and teaching support share one implementation, and a
new citable field cannot bypass the audit by being forgotten in a registry.

Time allocation and scheduling are deterministic for the same reason: the model emits relative
weights, and the backend does the arithmetic.

## Features

### Course and lecture context
- Courses with title, code, description, objectives, student level, total lectures and default
  lecture length (5–300 min).
- Lectures with topic, sequence number, duration, scheduled date, student-level override, notes and
  status (`planned`, `delivered`, `cancelled`, `merged`).
- A **Lecture details** tab to edit an existing lecture. Changing the duration re-fits the stored
  plan so it never shows a total that disagrees with the class length.

### Course material
- PDF upload (up to 50 MB; extension, `%PDF` header and non-empty checks) with optional title,
  authors and year, shown in citations.
- Background ingestion with live status (`pending` → `processing` → `indexed`, or `failed` with the
  reason). Scanned PDFs are rejected with a clear message rather than indexed as empty.
- Text cleaning (ligatures, smart quotes, bullets, junk glyphs), ~1000-character chunks with 150
  overlap, embedded with `gemini-embedding-2` (768 dimensions) and stored in ChromaDB.
- Delete a source and its vectors are removed.

### Structured lecture plans
- Plan = summary, learning objectives, prerequisites, ordered segments, likely misconceptions and
  clarification questions. Segment kinds are a closed set: `recap`, `concept`, `example`,
  `activity`, `check`, `summary`.
- **Exact time allocation.** The model gives a weight per segment; the backend apportions whole
  minutes (largest-remainder, 2-minute floor) that sum to exactly the class length at any duration.
- Prompts include course context, student level, lecture notes and the topics of earlier lectures.

### Professor control
- Edit a segment's title, body, kind or minutes; pin minutes (the rest rebalance); drop segments
  (the rest renumber and rebalance).
- Every change writes a **new plan version**; nothing is overwritten. Edits make no model call and
  keep existing citations.
- Regenerate produces a fresh plan from the course context, lecture notes and retrieved material.
  It does not currently read the professor's earlier edits — put instructions in the lecture notes.
- Approve or reject externally suggested resources.

### Chat
- A chat panel beside the live plan, with a thread per course and a lecture "in focus".
- **One model call per turn** returns the reply, its citations, an action and its arguments. The
  backend re-validates the action through the same Pydantic schemas the REST API uses and runs it
  through the same service functions, so **chat can do nothing the buttons could not do**. Invalid
  arguments are refused with an explanation, never half-applied.
- Actions: `update_lecture`, `create_lecture`, `generate_plan`, `edit_segments`, `drop_segments`,
  `update_course`, `generate_teaching_support`, `recommend_resources`, `recalibrate_schedule`, or
  `none` for questions and discussion.
- Context carried into each turn: course state, teaching calendar, lecture list, the open lecture's
  plan, and the last 10 messages.
- Changes apply immediately and the assistant states what it did; versioning makes that safe.
- **Two-sided interaction:** when an instruction is ambiguous the assistant asks one clarifying
  question and changes nothing that turn.
- Not an agentic tool loop: the free tier allows five generations per minute.

### Teaching support
Generated on demand per lecture and versioned. Every item carries grounding (or is labelled as a
model suggestion):
- **Industry applications**
- **Classroom activities** (pair, group, demo, poll, debate, think-pair-share) with rough minutes
  and instructions
- **Interactive presentation techniques**
- **Alternative explanations** for difficult concepts, with optional analogies

### External resource recommendations (Week 4)
- Ask the chat to recommend books, papers, videos or web pages. Each suggestion is checked against
  a public catalogue before it is added:
  - books — Open Library (ISBN, with a title-search fallback)
  - papers — Crossref (DOI)
  - videos — YouTube oEmbed (returns the real title and channel)
  - web pages — a HEAD request
- Verified items are stored as **pending** sources, with the catalogue's title replacing the
  model's, and appear in the sidebar with **Approve / Reject**. Items that cannot be verified are
  not added.
- Note: verification confirms the identifier exists; it does not judge relevance, and external
  sources have no passages, so they are a reading list rather than citable evidence.

### Schedule re-calibration (Week 5)
Deterministic date arithmetic, no model call.
- Teaching calendar per course: start date, optional end date, class weekdays, blocked dates with
  reasons.
- Handles **missed lectures**, **holidays / cancelled classes** and **changes in class length**.
- Rules: delivered lectures never move; a missed lecture goes back into the queue in its original
  order; remaining lectures take the next free class dates; if they no longer fit before the end
  date, the adjacent lectures holding the least material are merged (max 3 topics per class) and
  their plans combined and re-apportioned; spare dates are reported, not filled with invented
  topics.
- **Preview first, apply second:** the REST endpoint previews by default and writes only with
  `apply=true`; the UI has Preview and Apply buttons; the chat previews and asks before applying.
- Plans of lectures whose length changed are re-apportioned to the new duration.
- Refuses with a plain message when class days or the start date are not set.

### Interface
- Three-area layout — sidebar (courses, sources), chat, plan area with **Lecture plan /
  Teaching support / Lecture details** tabs and a **Schedule & re-calibration** panel; collapses to
  one column on narrow windows.
- Every form field has a persistent label, placeholder and hint.
- Citation chips with the verbatim passage; clarification prompts; plain-language rate-limit
  messages.

## Stack

React 19 + TypeScript + Tailwind 4 (Vite) · FastAPI · SQLAlchemy on SQLite · ChromaDB · PyMuPDF ·
Gemini `gemini-3.8-flash` (generation) and `gemini-embedding-2` (embeddings) over plain `httpx`.

**On the database.** The Phase 1 plan specifies PostgreSQL. The code uses SQLAlchemy against SQLite
so the project runs with zero setup; moving to PostgreSQL is intended to be a change to
`database_url` in `backend/app/config.py` (not yet tested).

**On the model.** Model ids were checked against the live API rather than taken from documentation:
on the development key `gemini-2.5-flash` returns 404 and the `google_search` grounding tool returns
429, so neither is used. Resource verification therefore uses keyless public catalogues (Open
Library, Crossref, YouTube oEmbed).

**On retrieval.** Top 12 chunks by cosine similarity, restricted to the course and its approved
sources.

## Project layout

```
backend/app/
  main.py            FastAPI app, CORS, routers, /api/health
  config.py          settings loaded from the root .env
  models.py          ORM tables
  schemas.py         request / response models
  routers/           courses, materials, lectures, chat
  services/
    ingest.py        PDF -> per-page chunks (PyMuPDF)
    embeddings.py    Gemini embeddings (thread pool, retry)
    vectorstore.py   VectorStore interface + Chroma implementation
    llm.py           Gemini JSON generation, retry / backoff, quota handling
    planner.py       retrieve -> generate -> enforce -> apportion -> persist
    grounding.py     pure citation-tag audit and scrub
    citations.py     citation strings from database metadata only
    timealloc.py     exact minute apportionment
    plan_edits.py    shared edit path for REST and chat
    lecture_ops.py   shared lecture create / update
    teaching_support.py
    chat.py          one chat turn, action validation and execution
    resource_verification.py   catalogue checks for suggested resources
    schedule.py      schedule re-calibration
  prompts/           lecture_plan, teaching_support, chat
backend/tests/       pytest suite
frontend/src/        App.tsx, components/, api/client.ts, types.ts
```

## Running it

Requires Python 3.10+ and Node 18+. Copy `.env.example` to `.env` at the repo root and set
`GEMINI_API_KEY`.

One-time setup (Windows):

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd frontend
npm install
```

Run the two servers in **separate terminals**, backend first. In Windows `cmd` or PowerShell:

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

In Git Bash, WSL, macOS or Linux, use forward slashes and the platform's venv path, e.g.
`../.venv/Scripts/python.exe` (Git Bash) or `../.venv/bin/python` (macOS / Linux). Activating the
virtualenv first lets you just run `uvicorn app.main:app --reload`.

First walkthrough: create a course → upload a PDF → wait for **indexed** → add a lecture →
**Generate lecture plan** → talk to the assistant ("make this 90 minutes", "drop segment 4") →
generate teaching support → set class days and dates in **Schedule & re-calibration** and try a
holiday.

Data lives in `data/` (uploads, Chroma index, `app.db`) and is git-ignored. Delete `data/app.db`
and `data/chroma` for a clean slate.

## API overview

Interactive docs at `/docs` while the backend runs.

| Area | Endpoints |
|---|---|
| Courses | `POST/GET /api/courses`, `GET/PATCH/DELETE /api/courses/{id}`, `POST /api/courses/{id}/recalibrate` |
| Materials | `POST/GET /api/courses/{id}/materials`, `DELETE /api/materials/{id}`, `PATCH /api/materials/{id}/approve`, `PATCH /api/materials/{id}/reject` |
| Lectures | `POST/GET /api/courses/{id}/lectures`, `GET/PATCH/DELETE /api/lectures/{id}` |
| Plans | `POST /api/lectures/{id}/plan/generate`, `GET/PATCH /api/lectures/{id}/plan`, `GET /api/lectures/{id}/plan/versions` |
| Teaching support | `POST/GET /api/lectures/{id}/teaching-support` |
| Chat | `POST/GET/DELETE /api/courses/{id}/chat`, `GET /api/courses/{id}/chat/citations` |
| Meta | `GET /api/health` |

## Tests

```
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

144 tests, no network and no API key required — the model is stubbed throughout, because what has to
be trustworthy is what the system does with model output, whatever the model returns on a given day.

| File | Verifies |
|---|---|
| `test_ingest.py` | Every passage's text really is on the page it claims, checked against the actual PDFs |
| `test_citations.py` | Rendered page numbers come from the database; model output cannot influence them |
| `test_grounding.py` | Invented tags are rejected; citable items nested at any depth are enforced |
| `test_planner.py` | Fabrication triggers a retry then degrades to ungrounded; plans fit the class |
| `test_timealloc.py` | Allocation sums to exactly the duration at any length |
| `test_llm.py` | Retry / backoff policy, quota handling, and that the API key travels in a header |
| `test_chat.py` | Instructions execute; invalid ones are refused not half-applied; fabricated citations are stripped; ambiguity asks back; history is replayed |
| `test_plan_edits.py` | The shared edit path: pinned minutes, renumbering, version semantics |
| `test_teaching_support.py` | Teaching support is grounded and its activity formats are a closed set |
| `test_schedule.py` | Holidays, missed lectures, delivered lectures fixed, merging, spare dates, preview changes nothing, chat previews before applying |

Not yet covered by automated tests: resource verification and a full end-to-end scenario.

## Known limitations

- **Grounding checks tags, not meaning.** A citation is guaranteed to point at a real retrieved
  passage on its real page; whether that passage supports the sentence is for the professor to
  judge from the verbatim snippet. Free text in model prose is constrained by the prompt, not
  scanned by code.
- **Page numbers are PDF page indexes**, which can differ from printed page numbers in a book.
- **PDF only; scanned PDFs are rejected** (no OCR).
- **Resource verification checks existence, not relevance.** The book title-search fallback
  accepts the top catalogue hit, and the video fallback accepts any HTTP 200 page. External
  sources cannot ground citations.
- **Regenerate does not use earlier professor edits**, and there is no per-segment regenerate or
  per-item accept / reject for plans.
- **`allowed_uses`** (what each source may be used for) is stored but not yet enforced.
- **Schedule re-calibration recalculates dates and minutes, not topics.** If a class becomes
  shorter than the number of segments, rebalancing is skipped. "Apply only after confirmation" in
  chat is enforced by the prompt; the REST endpoint previews by default.
- **Single professor, no login, SQLite, in-process background ingestion.**
