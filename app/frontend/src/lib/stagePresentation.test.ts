import { describe, expect, it } from 'vitest'
import { makeRecord } from '../test/fixtures'
import { stagePresentationOf, supportsCompletion } from './stagePresentation'

describe('stagePresentationOf', () => {
  it.each([
    ['pending_review', '创建于 2026-08-20'],
    ['applied', '投递于 2026-08-21'],
    ['offer', '结束于 2026-08-30'],
    ['rejected', '结束于 2026-08-30'],
    ['withdrawn', '结束于 2026-08-30'],
  ])('formats %s with its semantic date', (current_status, text) => {
    const record = makeRecord({
      current_status,
      submitted_at: '2026-08-21',
      latest_event: {
        stage: current_status,
        event_date: '2026-08-30',
        completed_date: null,
        scheduled_date: null,
        scheduled_time: null,
        deadline_date: null,
        deadline_time: null,
        mode: null,
        location: null,
        note: null,
        source: 'manual_ui',
      },
    })
    expect(stagePresentationOf(record).text).toBe(text)
  })

  it('uses assessment completion, plan, then deadline priority', () => {
    const base = makeRecord({
      current_status: 'assessment',
      latest_event: {
        stage: 'assessment',
        event_date: '2026-08-20',
        completed_date: '2026-08-23',
        scheduled_date: '2026-08-22',
        scheduled_time: null,
        deadline_date: '2026-08-25',
        deadline_time: null,
        mode: null,
        location: null,
        note: null,
        source: 'manual_ui',
      },
    })
    expect(stagePresentationOf(base)).toMatchObject({
      text: '笔试 / 测评 · 已完成',
      date: '2026-08-23',
      completed: true,
    })
    expect(stagePresentationOf({ ...base, latest_event: { ...base.latest_event!, completed_date: null } }).text)
      .toBe('笔试 / 测评 · 2026-08-22')
    expect(stagePresentationOf({
      ...base,
      latest_event: { ...base.latest_event!, completed_date: null, scheduled_date: null },
    }).text).toBe('截止 · 2026-08-25')
  })

  it.each([
    ['interview_1', '1面 · 已结束'],
    ['interview_2', '2面 · 已结束'],
    ['interview_3', '3面 · 已结束'],
    ['interview_hr', 'HR面 · 已结束'],
  ])('formats completed interview round %s', (current_status, text) => {
    const record = makeRecord({
      current_status,
      latest_event: {
        stage: current_status,
        event_date: '2026-08-20',
        completed_date: '2026-08-24',
        scheduled_date: '2026-08-24',
        scheduled_time: null,
        deadline_date: null,
        deadline_time: null,
        mode: null,
        location: null,
        note: null,
        source: 'manual_ui',
      },
    })
    expect(stagePresentationOf(record).text).toBe(text)
  })

  it('does not invent a fallback date', () => {
    const record = makeRecord({
      current_status: 'assessment',
      updated_at: '2026-08-31T18:00:00+08:00',
      latest_event: null,
    })
    expect(stagePresentationOf(record)).toMatchObject({ text: '笔试 / 测评', date: '' })
  })

  it('limits completion controls to assessment and exact interview rounds', () => {
    expect(supportsCompletion('assessment')).toBe(true)
    expect(supportsCompletion('interview_hr')).toBe(true)
    expect(supportsCompletion('applied')).toBe(false)
    expect(supportsCompletion('interview_unspecified')).toBe(false)
  })
})
