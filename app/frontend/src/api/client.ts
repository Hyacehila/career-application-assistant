const BASE_URL = '/api'

export const APPLICATION_TYPES = ['实习', '校招', '社招', '其他'] as const
export type ApplicationType = (typeof APPLICATION_TYPES)[number]

export interface ApplicationRecord {
  id: number
  company_name: string
  job_title: string
  department: string | null
  job_code: string | null
  application_type: string | null
  location: string | null
  source: string | null
  job_url: string | null
  current_status: string
  filled_at: string | null
  submitted_at: string | null
  next_action: string | null
  next_action_date: string | null
  notes: string | null
  created_at: string
  updated_at: string
  latest_event?: LatestEventSummary | null
}

export interface LatestEventSummary {
  stage: string
  event_date: string
  scheduled_date: string | null
  scheduled_time: string | null
  deadline_date: string | null
  deadline_time: string | null
  mode: string | null
  location: string | null
  note: string | null
  source: string
}

export interface BoardGroupCounts {
  pending_review: number
  applied: number
  assessment: number
  interview: number
  ended: number
}

export interface ListOptions {
  types: string[]
  cities: string[]
  sources: string[]
}

export interface ListApplicationsResponse {
  items: ApplicationRecord[]
  total: number
  page: number
  page_size: number
  counts: BoardGroupCounts
  options: ListOptions
}

export interface ApplicationDetail {
  application: ApplicationRecord
  events: ApplicationEvent[]
}

export interface ApplicationEvent {
  id: number
  stage: string
  event_date: string
  scheduled_date: string | null
  scheduled_time: string | null
  deadline_date: string | null
  deadline_time: string | null
  timezone: string
  mode: string | null
  location: string | null
  note: string | null
  source: string
  created_at: string
  updated_at: string
}

export interface EventPayload {
  stage: string
  event_date: string
  scheduled_date?: string | null
  scheduled_time?: string | null
  deadline_date?: string | null
  deadline_time?: string | null
  timezone?: string
  mode?: string | null
  location?: string | null
  note?: string | null
  source: string
}

export interface EventWriteResponse {
  application: ApplicationRecord
  event: ApplicationEvent
}

export type MailProvider = 'outlook' | 'qq' | '163'
export type HistoryWindow = 'new_only' | 'last_30_days' | 'last_90_days'
export type MailAccountStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'paused'
  | 'needs_reauth'
  | 'error'

export interface MailAccount {
  provider: MailProvider
  status: MailAccountStatus
  masked_address: string | null
  history_window: HistoryWindow
  last_attempt_at: string | null
  last_success_at: string | null
  next_retry_at: string | null
  error_code: string | null
  pending_count: number
}

export interface MailAccountsResponse {
  items: MailAccount[]
  pending_count: number
}

export type MailOperationKind = 'connect' | 'sync'
export type MailOperationStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export interface MailOperationAccepted {
  operation_id: string
  status: 'pending'
}

export interface MailOperation {
  id: string
  provider: MailProvider
  kind: MailOperationKind
  status: MailOperationStatus
  error_code?: string | null
}

export type MailCandidateState = 'pending' | 'committed' | 'dismissed' | 'expired' | 'duplicate'

export type ProposedMailStage =
  | 'applied'
  | 'assessment'
  | 'interview_unspecified'
  | 'interview_1'
  | 'interview_2'
  | 'interview_3'
  | 'interview_hr'
  | 'offer'
  | 'rejected'
  | 'withdrawn'

export interface MailCandidate {
  id: number
  provider: MailProvider
  state: MailCandidateState
  company_name: string | null
  job_title: string | null
  proposed_stage: ProposedMailStage | null
  event_date: string | null
  scheduled_date: string | null
  scheduled_time: string | null
  deadline_date: string | null
  deadline_time: string | null
  timezone: string
  confidence: number
  matched_application_id: number | null
  review_reasons: string[]
  expires_at: string | null
}

export interface MailCandidatesResponse {
  items: MailCandidate[]
  total: number
}

export interface ConnectOutlookPayload {
  client_id: string
  history_window: HistoryWindow
}

export interface ConnectImapPayload {
  mailbox_address: string
  authorization_code: string
  history_window: HistoryWindow
}

export type ConnectMailPayload = ConnectOutlookPayload | ConnectImapPayload

export interface ConfirmMailCandidatePayload {
  application_id: number
  stage: Exclude<ProposedMailStage, 'interview_unspecified'>
  scheduled_date?: string | null
  scheduled_time?: string | null
  deadline_date?: string | null
  deadline_time?: string | null
  timezone: string
  confirm_personally_submitted: boolean
}

export interface ConfirmMailCandidateResponse {
  candidate: MailCandidate
  application: ApplicationRecord
  event: ApplicationEvent
}

export interface ListApplicationsQuery {
  q?: string
  stageGroup?: string
  status?: string
  type?: string
  city?: string
  source?: string
  sort?: string
  page?: number
  pageSize?: number
  signal?: AbortSignal
}

export type ListAllApplicationsQuery = Omit<ListApplicationsQuery, 'page' | 'pageSize'>

export class APIError extends Error {
  readonly code: string
  readonly status?: number

  constructor(code: string, message: string, status?: number) {
    super(message)
    this.name = 'APIError'
    this.code = code
    this.status = status
  }
}

async function readJson(response: Response): Promise<unknown> {
  if (response.status === 204) return null
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    throw new APIError('invalid_json', '响应不是有效的 JSON 数据', response.status)
  }
}

function errorFromDetail(detail: unknown, status: number): APIError {
  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>
    const code = typeof record.code === 'string' && record.code ? record.code : `http_${status}`
    const message = typeof record.message === 'string' && record.message ? record.message : `请求失败（${status}）`
    return new APIError(code, message, status)
  }
  return new APIError(`http_${status}`, `请求失败（${status}）`, status)
}

function unwrap<T>(body: Response): Promise<T> {
  return readJson(body).then((parsed) => {
    if (!body.ok) throw errorFromDetail(parsed, body.status)
    return parsed as T
  })
}

function buildQueryString(query: Record<string, string | number | null | undefined>): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue
    if (typeof value === 'string') {
      if (value === '') continue
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    } else {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    }
  }
  return parts.length > 0 ? `?${parts.join('&')}` : ''
}

function request<T = unknown>(path: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return fetch(`${BASE_URL}${path}`, { ...init, headers, signal: signal ?? init.signal })
    .then((body: Response) => unwrap<T>(body))
    .catch((error: unknown) => {
      if (error instanceof APIError) throw error
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      throw new APIError('network_error', '无法连接后端服务')
    })
}

export function health(signal?: AbortSignal): Promise<unknown> {
  return request<unknown>('/health', { method: 'GET' }, signal)
}

export function listApplications(query: ListApplicationsQuery = {}): Promise<ListApplicationsResponse> {
  const { signal, ...filters } = query
  const search = buildQueryString({
    q: filters.q,
    stage_group: filters.stageGroup,
    status: filters.status,
    type: filters.type,
    city: filters.city,
    source: filters.source,
    sort: filters.sort,
    page: filters.page,
    page_size: filters.pageSize,
  })
  return request(`/applications${search}`, { method: 'GET' }, signal).then((parsed) => toListResponse(parsed))
}

const BOARD_PAGE_SIZE = 100

export async function listAllApplications(
  query: ListAllApplicationsQuery = {},
): Promise<ListApplicationsResponse> {
  const first = await listApplications({ ...query, page: 1, pageSize: BOARD_PAGE_SIZE })
  const pageCount = Math.ceil(first.total / BOARD_PAGE_SIZE)
  if (pageCount <= 1) return first

  const remaining = await Promise.all(
    Array.from({ length: pageCount - 1 }, (_, index) =>
      listApplications({ ...query, page: index + 2, pageSize: BOARD_PAGE_SIZE }),
    ),
  )
  const uniqueItems = new Map<number, ApplicationRecord>()
  for (const page of [first, ...remaining]) {
    for (const item of page.items) uniqueItems.set(item.id, item)
  }
  return {
    ...first,
    items: Array.from(uniqueItems.values()),
    page: 1,
    page_size: BOARD_PAGE_SIZE,
  }
}

function toNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function toStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []
}

function toListResponse(parsed: unknown): ListApplicationsResponse {
  const record = (parsed && typeof parsed === 'object' ? parsed : {}) as Record<string, unknown>
  const items = Array.isArray(record.items) ? record.items : Array.isArray(record.records) ? record.records : []
  const counts = (record.counts && typeof record.counts === 'object' ? record.counts : {}) as Record<string, unknown>
  const options = (record.options && typeof record.options === 'object' ? record.options : {}) as Record<string, unknown>
  return {
    items: items as ApplicationRecord[],
    total: toNumber(record.total, items.length),
    page: toNumber(record.page, 1),
    page_size: toNumber(record.page_size, 20),
    counts: {
      pending_review: toNumber(counts.pending_review, 0),
      applied: toNumber(counts.applied, 0),
      assessment: toNumber(counts.assessment, 0),
      interview: toNumber(counts.interview, 0),
      ended: toNumber(counts.ended, 0),
    },
    options: {
      types: toStringList(options.types),
      cities: toStringList(options.cities),
      sources: toStringList(options.sources),
    },
  }
}

function idSegment(id: number): string {
  return encodeURIComponent(String(id))
}

export function createApplication(body: Record<string, unknown>, signal?: AbortSignal): Promise<ApplicationRecord> {
  return request<ApplicationRecord>('/applications', { method: 'POST', body: JSON.stringify(body) }, signal)
}

export function getApplication(id: number, signal?: AbortSignal): Promise<ApplicationDetail> {
  return request(`/applications/${idSegment(id)}`, { method: 'GET' }, signal)
}

export function patchApplication(
  id: number,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<ApplicationRecord> {
  return request(`/applications/${idSegment(id)}`, { method: 'PATCH', body: JSON.stringify(body) }, signal)
}

export function deleteApplication(id: number, signal?: AbortSignal): Promise<unknown> {
  return request(`/applications/${idSegment(id)}`, { method: 'DELETE' }, signal)
}

export function postEvent(id: number, body: EventPayload, signal?: AbortSignal): Promise<EventWriteResponse> {
  return request(`/applications/${idSegment(id)}/events`, { method: 'POST', body: JSON.stringify(body) }, signal)
}

export function patchEvent(
  id: number,
  eventId: number,
  body: Partial<EventPayload>,
  signal?: AbortSignal,
): Promise<ApplicationEvent> {
  return request(
    `/applications/${idSegment(id)}/events/${idSegment(eventId)}`,
    { method: 'PATCH', body: JSON.stringify(body) },
    signal,
  )
}

function providerSegment(provider: MailProvider): string {
  return encodeURIComponent(provider)
}

export function listMailAccounts(signal?: AbortSignal): Promise<MailAccountsResponse> {
  return request('/mail/accounts', { method: 'GET' }, signal)
}

export function connectMailAccount(
  provider: MailProvider,
  body: ConnectMailPayload,
  signal?: AbortSignal,
): Promise<MailOperationAccepted> {
  return request(
    `/mail/accounts/${providerSegment(provider)}/connect`,
    { method: 'POST', body: JSON.stringify(body) },
    signal,
  )
}

export function getMailOperation(id: string, signal?: AbortSignal): Promise<MailOperation> {
  return request(`/mail/operations/${encodeURIComponent(id)}`, { method: 'GET' }, signal)
}

export function syncMailAccount(provider: MailProvider, signal?: AbortSignal): Promise<MailOperationAccepted> {
  return request(`/mail/accounts/${providerSegment(provider)}/sync`, { method: 'POST', body: '{}' }, signal)
}

export function pauseMailAccount(provider: MailProvider, signal?: AbortSignal): Promise<MailAccount> {
  return request(`/mail/accounts/${providerSegment(provider)}/pause`, { method: 'POST', body: '{}' }, signal)
}

export function resumeMailAccount(provider: MailProvider, signal?: AbortSignal): Promise<MailAccount> {
  return request(`/mail/accounts/${providerSegment(provider)}/resume`, { method: 'POST', body: '{}' }, signal)
}

export function disconnectMailAccount(provider: MailProvider, signal?: AbortSignal): Promise<void> {
  return request(`/mail/accounts/${providerSegment(provider)}`, { method: 'DELETE' }, signal)
}

export function listMailCandidates(state: MailCandidateState = 'pending', signal?: AbortSignal): Promise<MailCandidatesResponse> {
  const search = buildQueryString({ state })
  return request(`/mail/candidates${search}`, { method: 'GET' }, signal)
}

export function confirmMailCandidate(
  id: number,
  body: ConfirmMailCandidatePayload,
  signal?: AbortSignal,
): Promise<ConfirmMailCandidateResponse> {
  return request(
    `/mail/candidates/${idSegment(id)}/confirm`,
    { method: 'POST', body: JSON.stringify(body) },
    signal,
  )
}

export function dismissMailCandidate(id: number, signal?: AbortSignal): Promise<void> {
  return request(`/mail/candidates/${idSegment(id)}/dismiss`, { method: 'POST', body: '{}' }, signal)
}
