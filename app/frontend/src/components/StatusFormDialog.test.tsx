import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApplicationRecord } from '../api/client'
import { makeRecord } from '../test/fixtures'
import { jsonBody, okBody } from '../test/http'
import StatusFormDialog from './StatusFormDialog'

function setup(
  target: Parameters<typeof StatusFormDialog>[0]['target'],
  record: ApplicationRecord,
  onDone?: () => void,
  onError?: (message: string) => void,
) {
  return render(
    <StatusFormDialog target={target} record={record} onDone={onDone} onError={onError} onClose={() => {}} />,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('StatusFormDialog', () => {
  it('target=applied 显示确认文案，确认后提交 applied 事件', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okBody({ id: 1, stage: 'applied' }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const onDone = vi.fn()
    setup('applied', makeRecord({ id: 5 }), onDone)
    expect(screen.getByText('请确认你已经手动完成最终提交', { exact: false })).toBeInTheDocument()
    const confirmation = screen.getByRole('checkbox', { name: '我确认已亲自完成最终提交' })
    expect(screen.getByRole('button', { name: '确认更新' })).toBeDisabled()
    await user.click(confirmation)
    const eventDate = screen.getByTestId('status-form-event-date') as HTMLInputElement
    expect(eventDate.value).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    await user.click(screen.getByRole('button', { name: '确认更新' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(onDone).toHaveBeenCalled()
    })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/applications/5/events')
    expect(JSON.parse(String(init.body))).toMatchObject({ stage: 'applied', source: 'user_confirmation' })
  })

  it('target=assessment 时计划日期与截止日期都未填写则禁用提交并提示', () => {
    setup('assessment', makeRecord({ id: 6 }))
    const submit = screen.getByTestId('status-form-submit')
    expect(submit).toBeDisabled()
    expect(screen.getByTestId('status-form-scheduled-time')).toBeDisabled()
    expect(screen.getByTestId('status-form-deadline-time')).toBeDisabled()
    expect(screen.getByTestId('status-form-assessment-hint')).toBeInTheDocument()
  })

  it('target=assessment 填写截止日期后可提交', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okBody({ id: 1, stage: 'assessment' }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    setup('assessment', makeRecord({ id: 6 }))
    fireEvent.change(screen.getByTestId('status-form-deadline-date'), { target: { value: '2026-09-15' } })
    const submit = screen.getByTestId('status-form-submit')
    expect(submit).toBeEnabled()
    await user.click(submit)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      stage: 'assessment',
      deadline_date: '2026-09-15',
    })
  })

  it('target=interview 轮次与面试日期必填，选择轮次+日期后可提交', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okBody({ id: 1, stage: 'interview_1' }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    setup('interview', makeRecord({ id: 7 }))
    expect(screen.getByText('面试轮次（必填）')).toBeInTheDocument()
    expect(screen.getByTestId('status-form-event-date')).toBeRequired()
    expect(screen.getByTestId('status-form-scheduled-date')).toBeRequired()
    expect(screen.getByTestId('status-form-scheduled-time')).toBeDisabled()
    const submit = screen.getByTestId('status-form-submit')
    expect(submit).toBeDisabled()
    expect(screen.getByTestId('status-form-interview-hint')).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('status-form-scheduled-date'), { target: { value: '2026-09-01' } })
    expect(screen.getByTestId('status-form-scheduled-time')).toBeEnabled()
    expect(submit).toBeEnabled()
    await user.click(screen.getByRole('radio', { name: '2面' }))
    fireEvent.change(screen.getByTestId('status-form-scheduled-time'), { target: { value: '14:30' } })
    await user.selectOptions(screen.getByLabelText('面试方式（可选）'), '线上')
    await user.click(submit)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      stage: 'interview_2',
      scheduled_date: '2026-09-01',
      scheduled_time: '14:30',
      mode: 'online',
    })
  })

  it('target=ended 显示结果单选（Offer/拒绝/撤回）', () => {
    setup('ended', makeRecord({ id: 8 }))
    expect(screen.getByRole('radio', { name: 'Offer' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '拒绝' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '撤回' })).toBeInTheDocument()
  })

  it('free 模式默认选中当前状态，10 个状态按分组可勾选', () => {
    setup('free', makeRecord({ id: 9, current_status: 'interview_1' }))
    expect(screen.getByRole('radio', { name: '1面' })).toBeChecked()
    expect(screen.getByRole('radio', { name: '待确认投递' })).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'HR面' })).toBeInTheDocument()
  })

  it('free 模式选择已投递后要求明确确认并使用 user_confirmation', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okBody({ id: 1, stage: 'applied' }))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    setup('free', makeRecord({ id: 11, current_status: 'pending_review' }))
    await user.click(screen.getByRole('radio', { name: '已投递' }))
    expect(screen.getByText('请确认你已经手动完成最终提交', { exact: false })).toBeInTheDocument()
    const submit = screen.getByTestId('status-form-submit')
    expect(submit).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: '我确认已亲自完成最终提交' }))
    expect(submit).toBeEnabled()
    await user.click(submit)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
      stage: 'applied',
      source: 'user_confirmation',
    })
  })

  it('提交返回 422 时展示后端 message 且保持打开', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonBody({ code: 'validation_error', message: '面试必须填写计划日期' }, 422))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    setup('interview', makeRecord({ id: 10 }))
    fireEvent.change(screen.getByTestId('status-form-scheduled-date'), { target: { value: '2026-09-01' } })
    await user.click(screen.getByTestId('status-form-submit'))
    await waitFor(() => {
      expect(screen.getByTestId('status-form-error')).toHaveTextContent('面试必须填写计划日期')
    })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
