import { describe, expect, it } from 'vitest'
import { formatDate, formatDateTime, formatTime, isIsoDate, isIsoTime } from './dates'

describe('dates', () => {
  it('格式化 ISO 日期', () => {
    expect(formatDate('2026-08-27')).toBe('2026-08-27')
    expect(formatDate('2026-08-27T10:30:00+08:00')).toBe('2026-08-27')
    expect(formatDate('2026/08/27 10:30')).toBe('')
  })

  it('格式化时间', () => {
    expect(formatTime('2026-08-27T10:30:00+08:00')).toBe('10:30')
    expect(formatTime('10:30')).toBe('10:30')
    expect(formatTime(undefined)).toBe('')
    expect(formatTime(null)).toBe('')
  })

  it('组合日期时间', () => {
    expect(formatDateTime('2026-08-27T10:30:00')).toBe('2026-08-27 10:30')
    expect(formatDateTime('')).toBe('')
  })

  it('ISO 格式校验', () => {
    expect(isIsoDate('2026-08-27')).toBe(true)
    expect(isIsoDate('2026/08/27')).toBe(false)
    expect(isIsoTime('09:05')).toBe(true)
    expect(isIsoTime('9:05')).toBe(false)
  })
})