import { describe, expect, it } from 'vitest'
import {
  BOARD_GROUP_LABELS,
  BOARD_GROUPS,
  STATUSES,
  STATUS_TO_BOARD_GROUP,
  boardGroupOf,
  semanticColorOf,
  statusLabelOf,
} from './statuses'

describe('statuses', () => {
  const expectedGroups: Record<string, string> = {
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

  it('10 个状态正确映射到 5 个看板分组', () => {
    expect(STATUSES).toHaveLength(10)
    expect(BOARD_GROUPS).toHaveLength(5)
    for (const status of STATUSES) {
      expect(boardGroupOf(status)).toBe(expectedGroups[status])
      expect(STATUS_TO_BOARD_GROUP[status]).toBe(expectedGroups[status])
    }
    const usedGroups = new Set(STATUSES.map((status) => STATUS_TO_BOARD_GROUP[status]))
    expect([...usedGroups].sort()).toEqual([...BOARD_GROUPS].sort())
  })

  it('语义色映射', () => {
    expect(semanticColorOf('offer')).toBe('#14A67A')
    expect(semanticColorOf('rejected')).toBe('#EF4B52')
    expect(semanticColorOf('withdrawn')).toBe('#8A94A6')
    expect(semanticColorOf('assessment')).toBe('#0F9B96')
    expect(semanticColorOf('interview_1')).toBe('#F5A400')
    expect(semanticColorOf('interview_hr')).toBe('#F5A400')
    expect(semanticColorOf('pending_review')).toBe('#0F9B96')
    expect(semanticColorOf('applied')).toBe('#1768E8')
  })

  it('中文显示名', () => {
    expect(statusLabelOf('pending_review')).toBe('待人工复核')
    expect(statusLabelOf('interview_3')).toBe('3面')
    expect(statusLabelOf('offer')).toBe('Offer')
    expect(BOARD_GROUP_LABELS.assessment).toBe('笔试 / 测评')
    expect(BOARD_GROUP_LABELS.interview).toBe('面试')
    expect(BOARD_GROUP_LABELS.ended).toBe('已结束')
  })
})
