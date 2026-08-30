export const STATUSES = [
  'pending_review',
  'applied',
  'assessment',
  'interview_1',
  'interview_2',
  'interview_3',
  'interview_hr',
  'offer',
  'rejected',
  'withdrawn',
] as const

export type Status = (typeof STATUSES)[number]

export const BOARD_GROUPS = [
  'pending_review',
  'applied',
  'assessment',
  'interview',
  'ended',
] as const

export type BoardGroup = (typeof BOARD_GROUPS)[number]

export const STATUS_TO_BOARD_GROUP: Record<Status, BoardGroup> = {
  pending_review: 'pending_review',
  applied: 'applied',
  assessment: 'assessment',
  interview_1: 'interview',
  interview_2: 'interview',
  interview_3: 'interview',
  interview_hr: 'interview',
  offer: 'ended',
  rejected: 'ended',
  withdrawn: 'ended',
}

export const STATUS_LABELS: Record<Status, string> = {
  pending_review: '待确认投递',
  applied: '已投递',
  assessment: '笔试 / 测评',
  interview_1: '1面',
  interview_2: '2面',
  interview_3: '3面',
  interview_hr: 'HR面',
  offer: 'Offer',
  rejected: '拒绝',
  withdrawn: '撤回',
}

export const BOARD_GROUP_LABELS: Record<BoardGroup, string> = {
  pending_review: '待确认投递',
  applied: '已投递',
  assessment: '笔试 / 测评',
  interview: '面试',
  ended: '已结束',
}

const ACCENT_TEAL = '#0F9B96'
const INTERVIEW_ORANGE = '#F5A400'
const OFFER_GREEN = '#14A67A'
const REJECTED_RED = '#EF4B52'
const NEUTRAL_GRAY = '#8A94A6'

export const STATUS_SEMANTIC_COLORS: Record<Status, string> = {
  pending_review: ACCENT_TEAL,
  applied: '#1768E8',
  assessment: ACCENT_TEAL,
  interview_1: INTERVIEW_ORANGE,
  interview_2: INTERVIEW_ORANGE,
  interview_3: INTERVIEW_ORANGE,
  interview_hr: INTERVIEW_ORANGE,
  offer: OFFER_GREEN,
  rejected: REJECTED_RED,
  withdrawn: NEUTRAL_GRAY,
}

export function boardGroupOf(status: string): BoardGroup {
  return STATUS_TO_BOARD_GROUP[status as Status] ?? 'applied'
}

export function statusLabelOf(status: string): string {
  return STATUS_LABELS[status as Status] ?? status
}

export function semanticColorOf(status: string): string {
  return STATUS_SEMANTIC_COLORS[status as Status] ?? NEUTRAL_GRAY
}
