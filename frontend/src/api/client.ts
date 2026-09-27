import type {
  ChatMessage,
  ChatTurn,
  Citation,
  Course,
  Lecture,
  Plan,
  Source,
  TeachingSupport,
} from '../types'

const BASE = '/api'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
    ...init,
  })

  if (!response.ok) {
    // FastAPI puts the useful message in `detail`; surface it rather than a status code.
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status)
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; model: string }>('/health'),

  listCourses: () => request<Course[]>('/courses'),
  createCourse: (body: Partial<Course>) =>
    request<Course>('/courses', { method: 'POST', body: JSON.stringify(body) }),
  deleteCourse: (id: number) => request<void>(`/courses/${id}`, { method: 'DELETE' }),

  listMaterials: (courseId: number) => request<Source[]>(`/courses/${courseId}/materials`),
  uploadMaterial: (courseId: number, form: FormData) =>
    request<Source>(`/courses/${courseId}/materials`, { method: 'POST', body: form }),
  deleteMaterial: (sourceId: number) =>
    request<void>(`/materials/${sourceId}`, { method: 'DELETE' }),

  listLectures: (courseId: number) => request<Lecture[]>(`/courses/${courseId}/lectures`),
  createLecture: (courseId: number, body: Record<string, unknown>) =>
    request<Lecture>(`/courses/${courseId}/lectures`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateLecture: (id: number, body: Record<string, unknown>) =>
    request<Lecture>(`/lectures/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteLecture: (id: number) => request<void>(`/lectures/${id}`, { method: 'DELETE' }),

  getPlan: (lectureId: number) => request<Plan>(`/lectures/${lectureId}/plan`),
  generatePlan: (lectureId: number) =>
    request<Plan>(`/lectures/${lectureId}/plan/generate`, { method: 'POST' }),
  editPlan: (lectureId: number, body: Record<string, unknown>) =>
    request<Plan>(`/lectures/${lectureId}/plan`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
}

export const teachingSupportApi = {
  get: (lectureId: number) =>
    request<TeachingSupport>(`/lectures/${lectureId}/teaching-support`),
  generate: (lectureId: number) =>
    request<TeachingSupport>(`/lectures/${lectureId}/teaching-support`, {
      method: 'POST',
    }),
}

export const chatApi = {
  history: (courseId: number) => request<ChatMessage[]>(`/courses/${courseId}/chat`),
  citations: (courseId: number) =>
    request<Record<string, Citation>>(`/courses/${courseId}/chat/citations`),
  send: (courseId: number, message: string, lectureId: number | null) =>
    request<ChatTurn>(`/courses/${courseId}/chat`, {
      method: 'POST',
      body: JSON.stringify({ message, lecture_id: lectureId }),
    }),
  clear: (courseId: number) =>
    request<void>(`/courses/${courseId}/chat`, { method: 'DELETE' }),
}
