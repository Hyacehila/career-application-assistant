import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ApplicationRecord } from '../api/client'
import { makeRecord } from '../test/fixtures'
import { jsonBody, okBody } from '../test/http'
import RecordFormDialog from './RecordFormDialog'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RecordFormDialog', () => {
  it('新增模式：公司/岗位为空时提交按钮禁用', () => {
    render(<RecordFormDialog mode="create" onClose={() => {}} />)
    expect(screen.getByText('新增记录')).toBeInTheDocument()
    expect(screen.getByText(/默认进入“待确认投递”/)).toBeInTheDocument()
    const submit = screen.getByTestId('record-form-submit')
    expect(submit).toBeDisabled()
  })

  it('新增模式：填写公司与岗位后可提交，携带 event_date=今天', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okBody(makeRecord()))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const onDone = vi.fn()
    render(<RecordFormDialog mode="create" onClose={() => {}} onDone={onDone} />)
    await user.type(screen.getByTestId('record-form-company'), '示例科技')
    await user.type(screen.getByTestId('record-form-job'), '前端工程师')
    await user.type(screen.getByTestId('record-form-next-action'), '准备技术面试')
    fireEvent.change(screen.getByTestId('record-form-next-action-date'), {
      target: { value: '2026-09-10' },
    })
    await user.type(screen.getByTestId('record-form-notes'), '关注流程日期')
    const submit = screen.getByTestId('record-form-submit')
    expect(submit).toBeEnabled()
    await user.click(submit)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
      expect(onDone).toHaveBeenCalled()
    })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/applications')
    const body = JSON.parse(String(init.body))
    expect(body).toMatchObject({ company_name: '示例科技', job_title: '前端工程师' })
    expect(body).toMatchObject({
      next_action: '准备技术面试',
      next_action_date: '2026-09-10',
      notes: '关注流程日期',
    })
    expect(body.event_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('编辑模式：标题为“编辑记录”，提交调用 PATCH 且不带 event_date', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okBody(makeRecord()))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const record = makeRecord({
      id: 3,
      company_name: '示例科技',
      job_title: '前端工程师',
      next_action: '完成测评',
      next_action_date: '2026-09-02',
      notes: '只保存结构化备注',
    })
    render(<RecordFormDialog mode="edit" record={record} onClose={() => {}} />)
    expect(screen.getByText('编辑记录')).toBeInTheDocument()
    expect(screen.getByTestId('record-form-company')).toHaveValue('示例科技')
    expect(screen.getByTestId('record-form-next-action')).toHaveValue('完成测评')
    expect(screen.getByTestId('record-form-next-action-date')).toHaveValue('2026-09-02')
    expect(screen.getByTestId('record-form-notes')).toHaveValue('只保存结构化备注')
    await user.click(screen.getByTestId('record-form-submit'))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/applications/3')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(String(init.body)).event_date).toBeUndefined()
  })

  it('提交失败时显示错误信息且保持打开', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonBody({ code: 'name_conflict', message: '记录已存在' }, 409))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const onError = vi.fn()
    render(<RecordFormDialog mode="create" onClose={() => {}} onError={onError} />)
    await user.type(screen.getByTestId('record-form-company'), '示例科技')
    await user.type(screen.getByTestId('record-form-job'), '前端工程师')
    await user.click(screen.getByTestId('record-form-submit'))
    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith('记录已存在')
    })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
