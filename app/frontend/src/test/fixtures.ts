import type { ApplicationRecord, ApplicationEvent } from '../api/client'

export function makeRecord(overrides: Partial<ApplicationRecord> = {}): ApplicationRecord {
  return {
    id: 1,
    company_name: '示例科技',
    job_title: '前端工程师',
    department: null,
    job_code: null,
    application_type: '校招',
    location: '上海',
    source: '官方网站',
    job_url: 'https://example.com/career/frontend',
    current_status: 'pending_review',
    filled_at: '2026-08-20T09:00:00+08:00',
    submitted_at: null,
    next_action: null,
    next_action_date: null,
    notes: null,
    created_at: '2026-08-20T09:00:00+08:00',
    updated_at: '2026-08-20T09:00:00+08:00',
    ...overrides,
  }
}

export function makeEvent(overrides: Partial<ApplicationEvent> = {}): ApplicationEvent {
  return {
    id: 11,
    stage: 'pending_review',
    event_date: '2026-08-20',
    completed_date: null,
    scheduled_date: null,
    scheduled_time: null,
    deadline_date: null,
    deadline_time: null,
    timezone: 'Asia/Shanghai',
    mode: null,
    location: null,
    note: null,
    source: 'agent_fill',
    created_at: '2026-08-20T09:00:00+08:00',
    updated_at: '2026-08-20T09:00:00+08:00',
    ...overrides,
  }
}
