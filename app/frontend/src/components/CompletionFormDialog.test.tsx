import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { todayDate } from '../lib/dates'
import { makeEvent, makeRecord } from '../test/fixtures'
import { jsonBody } from '../test/http'
import CompletionFormDialog from './CompletionFormDialog'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('CompletionFormDialog', () => {
  it('defaults to Shanghai today and saves assessment completion', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonBody(makeEvent({ completed_date: todayDate() })))
    vi.stubGlobal('fetch', fetchMock)
    const onDone = vi.fn()
    render(
      <CompletionFormDialog
        record={makeRecord({ current_status: 'assessment' })}
        event={makeEvent({ id: 31, stage: 'assessment', deadline_date: '2026-09-05' })}
        onDone={onDone}
        onClose={() => {}}
      />,
    )
    const input = screen.getByTestId('completion-form-date')
    expect(input).toHaveValue(todayDate())
    expect(input).toHaveAttribute('max', todayDate())
    await userEvent.click(screen.getByTestId('completion-form-submit'))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/applications/1/events/31',
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ completed_date: todayDate() }) }),
    )
    expect(onDone).toHaveBeenCalledWith('完成状态已保存')
  })

  it('allows an existing interview completion date to be changed or cleared', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonBody(makeEvent({ completed_date: null })))
    vi.stubGlobal('fetch', fetchMock)
    const onDone = vi.fn()
    render(
      <CompletionFormDialog
        record={makeRecord({ current_status: 'interview_2' })}
        event={makeEvent({ id: 32, stage: 'interview_2', completed_date: '2026-08-28' })}
        onDone={onDone}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/2面 · 已结束/)).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('completion-form-clear'))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/applications/1/events/32',
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ completed_date: null }) }),
    )
    expect(onDone).toHaveBeenCalledWith('已撤销完成标记')
  })

  it('keeps the dialog open and shows a safe API error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonBody({
      code: 'validation_error',
      message: '完成日期不能晚于今天',
    }, 422)))
    const onDone = vi.fn()
    const onError = vi.fn()
    render(
      <CompletionFormDialog
        record={makeRecord({ current_status: 'assessment' })}
        event={makeEvent({ id: 33, stage: 'assessment', deadline_date: '2026-09-05' })}
        onDone={onDone}
        onError={onError}
        onClose={() => {}}
      />,
    )
    await userEvent.click(screen.getByTestId('completion-form-submit'))
    expect(await screen.findByRole('alert')).toHaveTextContent('完成日期不能晚于今天')
    expect(onDone).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith('完成日期不能晚于今天')
  })
})
