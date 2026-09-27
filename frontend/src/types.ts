export interface Course {
  id: number
  title: string
  code: string
  description: string
  objectives: string
  student_level: string
  total_lectures: number | null
  lecture_duration_min: number
  created_at: string
}

export interface DocumentInfo {
  id: number
  filename: string
  page_count: number
  chunk_count: number
  ingest_status: 'pending' | 'processing' | 'ready' | 'failed'
  ingest_error: string
  created_at: string
}

export interface Source {
  id: number
  kind: string
  title: string
  authors: string
  year: number | null
  identifier: string
  status: 'pending' | 'approved' | 'rejected'
  allowed_uses: string[]
  documents: DocumentInfo[]
}

export interface Lecture {
  id: number
  course_id: number
  seq_no: number
  topic: string
  duration_min: number
  scheduled_date: string | null
  student_level_override: string
  notes: string
  status: string
  has_plan: boolean
}

/** Built by the backend from parsed document metadata, never from model output. */
export interface Citation {
  chunk_id: number
  source_id: number
  source_title: string
  authors: string
  year: number | null
  kind: string
  identifier: string
  document_filename: string
  page_no: number
  snippet: string
  display: string
}

export type SegmentKind =
  | 'recap'
  | 'concept'
  | 'example'
  | 'activity'
  | 'check'
  | 'summary'

export interface Segment {
  ordinal: number
  kind: SegmentKind
  title: string
  body: string
  minutes: number
  grounding: number[]
  edited_by_professor?: boolean
}

export interface GroundedText {
  text: string
  grounding: number[]
}

export interface Clarification {
  field: string
  question: string
}

export interface PlanBody {
  topic: string
  summary: string
  duration_min: number
  total_allocated_min: number
  learning_objectives: GroundedText[]
  prerequisites: GroundedText[]
  segments: Segment[]
  misconceptions: GroundedText[]
  clarifications_needed: Clarification[]
}

export interface Plan {
  id: number
  lecture_id: number
  version: number
  model: string
  created_at: string
  plan: PlanBody
  citations: Record<string, Citation>
  grounded_segment_count: number
  total_segment_count: number
  retrieved_chunk_count: number
}

// --- Teaching support (Week 3) ----------------------------------------------

export type ActivityFormat =
  | 'pair'
  | 'group'
  | 'demo'
  | 'poll'
  | 'debate'
  | 'think_pair_share'

export interface IndustryApplication {
  title: string
  text: string
  grounding: number[]
}

export interface Activity {
  title: string
  format: ActivityFormat
  minutes: number
  instructions: string
  grounding: number[]
}

export interface AltExplanation {
  concept: string
  explanation: string
  analogy: string
  grounding: number[]
}

export interface SupportBody {
  industry_applications: IndustryApplication[]
  activities: Activity[]
  interactive_techniques: GroundedText[]
  alt_explanations: AltExplanation[]
}

export interface TeachingSupport {
  id: number
  lecture_id: number
  version: number
  model: string
  created_at: string
  support: SupportBody
  citations: Record<string, Citation>
  retrieved_chunk_count: number
}

// --- Chat --------------------------------------------------------------------

export interface ChatAction {
  action: string
  summary?: string
  refused?: string
}

export interface ChatMessage {
  id: number
  role: 'professor' | 'assistant'
  content: string
  lecture_id: number | null
  citations: number[]
  action: ChatAction | null
  clarification: string
  created_at: string
}

export interface ChatTurn {
  message: ChatMessage
  citations: Record<string, Citation>
  focus_lecture_id: number | null
  plan_changed: boolean
  lecture_changed: boolean
  course_changed: boolean
  support_changed: boolean
}
