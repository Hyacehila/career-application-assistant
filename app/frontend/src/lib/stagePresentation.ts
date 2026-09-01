import type { ApplicationRecord } from '../api/client'
import { formatDate } from './dates'
import { semanticColorOf, statusLabelOf } from './statuses'

export interface StagePresentation {
  label: string
  text: string
  date: string
  color: string
  completed: boolean
}

const INTERVIEW_STAGES = new Set([
  'interview_1',
  'interview_2',
  'interview_3',
  'interview_hr',
])
const ENDED_STAGES = new Set(['offer', 'rejected', 'withdrawn'])

function result(record: ApplicationRecord, text: string, date = '', completed = false): StagePresentation {
  return {
    label: statusLabelOf(record.current_status),
    text,
    date,
    color: semanticColorOf(record.current_status),
    completed,
  }
}

export function stagePresentationOf(record: ApplicationRecord): StagePresentation {
  const stage = record.current_status
  const label = statusLabelOf(stage)
  const latest = record.latest_event

  if (stage === 'pending_review') {
    const date = formatDate(record.created_at)
    return result(record, date ? `创建于 ${date}` : label, date)
  }

  if (stage === 'applied') {
    const date = formatDate(record.submitted_at) || formatDate(latest?.event_date)
    return result(record, date ? `投递于 ${date}` : label, date)
  }

  if (stage === 'assessment') {
    const completedDate = formatDate(latest?.completed_date)
    if (completedDate) return result(record, `${label} · 已完成`, completedDate, true)
    const scheduledDate = formatDate(latest?.scheduled_date)
    if (scheduledDate) return result(record, `${label} · ${scheduledDate}`, scheduledDate)
    const deadlineDate = formatDate(latest?.deadline_date)
    if (deadlineDate) return result(record, `截止 · ${deadlineDate}`, deadlineDate)
    return result(record, label)
  }

  if (INTERVIEW_STAGES.has(stage)) {
    const completedDate = formatDate(latest?.completed_date)
    if (completedDate) return result(record, `${label} · 已结束`, completedDate, true)
    const scheduledDate = formatDate(latest?.scheduled_date)
    if (scheduledDate) return result(record, `${label} · ${scheduledDate}`, scheduledDate)
    return result(record, label)
  }

  if (ENDED_STAGES.has(stage)) {
    const date = formatDate(latest?.event_date)
    return result(record, date ? `结束于 ${date}` : label, date, true)
  }

  return result(record, label)
}

export function supportsCompletion(stage: string): boolean {
  return stage === 'assessment' || INTERVIEW_STAGES.has(stage)
}
