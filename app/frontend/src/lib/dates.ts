export function formatDate(value: string | null | undefined): string {
  if (!value) return ''
  const match = value.match(/^(\d{4}-\d{2}-\d{2})/)
  return match ? match[1] : ''
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return ''
  const dateTimeMatch = value.match(/^\d{4}-\d{2}-\d{2}[T ](\d{2}:\d{2})/)
  if (dateTimeMatch) return dateTimeMatch[1]
  const timeMatch = value.match(/^(\d{2}:\d{2})/)
  return timeMatch ? timeMatch[1] : ''
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = formatDate(value)
  const time = formatTime(value)
  if (date && time) return `${date} ${time}`
  return date || time
}

export function isEmptyDate(value: string | null | undefined): boolean {
  return !value || value.trim() === ''
}

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/
const TIME_PATTERN = /^\d{2}:\d{2}$/

export function isIsoDate(value: string | null | undefined): boolean {
  return typeof value === 'string' && DATE_PATTERN.test(value)
}

export function isIsoTime(value: string | null | undefined): boolean {
  return typeof value === 'string' && TIME_PATTERN.test(value)
}

export function todayDate(timeZone = 'Asia/Shanghai'): string {
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(new Date())
  } catch {
    const now = new Date()
    const pad = (value: number) => String(value).padStart(2, '0')
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  }
}
