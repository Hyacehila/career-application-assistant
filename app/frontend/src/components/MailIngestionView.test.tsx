import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MailIngestionView from './MailIngestionView'
import { jsonBody } from '../test/http'
import { makeRecord } from '../test/fixtures'
import type { MailAccount, MailCandidate } from '../api/client'

const FIXTURE_MAILBOX = ['fixture-user', 'qq.example'].join('@')

const disconnectedAccounts: MailAccount[] = [
  {
    provider: 'outlook',
    status: 'disconnected',
    masked_address: null,
    history_window: 'new_only',
    last_attempt_at: null,
    last_success_at: null,
    next_retry_at: null,
    error_code: null,
    pending_count: 0,
  },
  {
    provider: 'qq',
    status: 'disconnected',
    masked_address: null,
    history_window: 'new_only',
    last_attempt_at: null,
    last_success_at: null,
    next_retry_at: null,
    error_code: null,
    pending_count: 0,
  },
  {
    provider: '163',
    status: 'disconnected',
    masked_address: null,
    history_window: 'new_only',
    last_attempt_at: null,
    last_success_at: null,
    next_retry_at: null,
    error_code: null,
    pending_count: 0,
  },
]

function pendingCandidate(overrides: Partial<MailCandidate> = {}): MailCandidate {
  return {
    id: 9,
    provider: 'outlook',
    state: 'pending',
    company_name: '示例科技',
    job_title: '后端工程师',
    proposed_stage: 'interview_unspecified',
    event_date: '2026-08-29',
    scheduled_date: null,
    scheduled_time: null,
    deadline_date: null,
    deadline_time: null,
    timezone: 'Asia/Shanghai',
    confidence: 83,
    matched_application_id: 44,
    review_reasons: ['generic_interview'],
    expires_at: '2026-11-27T12:00:00+08:00',
    ...overrides,
  }
}

function setupFetch(
  candidateItems: unknown[] = [],
  extra?: (url: string, init?: RequestInit) => Response | Promise<Response> | undefined,
) {
  const application = makeRecord({ id: 44, company_name: '示例科技', job_title: '后端工程师' })
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const override = extra?.(url, init)
    if (override) return Promise.resolve(override)
    if (url === '/api/mail/accounts' && init?.method === 'GET') {
      return Promise.resolve(jsonBody({ items: disconnectedAccounts, pending_count: candidateItems.length }))
    }
    if (url === '/api/mail/candidates?state=pending' && init?.method === 'GET') {
      return Promise.resolve(jsonBody({ items: candidateItems, total: candidateItems.length }))
    }
    if (url === '/api/applications?sort=-updated_at&page=1&page_size=100' && init?.method === 'GET') {
      return Promise.resolve(jsonBody({
        items: [application],
        total: 1,
        page: 1,
        page_size: 100,
        counts: { pending_review: 1, applied: 0, assessment: 0, interview: 0, ended: 0 },
        options: { types: [], cities: [], sources: [] },
      }))
    }
    throw new Error(`unexpected request: ${init?.method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('MailIngestionView', () => {
  it('首次账户状态加载失败时不显示可操作的未连接卡片', async () => {
    setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts' && init?.method === 'GET') {
        return jsonBody({ code: 'mail_accounts_unavailable', message: 'fixture failure' }, 500)
      }
    })
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    expect(await screen.findByText('无法确认邮箱连接状态')).toBeInTheDocument()
    expect(screen.queryByRole('article', { name: 'Outlook' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '连接邮箱' })).not.toBeInTheDocument()
    expect(screen.getByText(/连接状态确认前不会显示或提交/)).toBeInTheDocument()
  })

  it('需要重新授权时保留历史范围，并仍可安全断开', async () => {
    const accounts = disconnectedAccounts.map((account) => account.provider === 'qq'
      ? {
          ...account,
          status: 'needs_reauth' as const,
          masked_address: 'f***@q***.com',
          history_window: 'last_90_days' as const,
          error_code: 'imap_reauth_required',
        }
      : account)
    setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts' && init?.method === 'GET') {
        return jsonBody({ items: accounts, pending_count: 0 })
      }
    })
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const card = await screen.findByRole('article', { name: 'QQ 邮箱' })
    expect(within(card).getByLabelText('首次读取范围')).toHaveValue('last_90_days')
    expect(within(card).getByRole('button', { name: '断开' })).toBeEnabled()
  })

  it('取消重新授权时清空邮箱地址和授权码并返回恢复操作', async () => {
    const accounts = disconnectedAccounts.map((account) => account.provider === '163'
      ? { ...account, status: 'paused' as const, masked_address: 'f***@1***.com' }
      : account)
    setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts' && init?.method === 'GET') {
        return jsonBody({ items: accounts, pending_count: 0 })
      }
    })
    const user = userEvent.setup()
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const card = await screen.findByRole('article', { name: '163 邮箱' })
    await user.click(within(card).getByRole('button', { name: '重新授权' }))
    expect(within(card).getByRole('button', { name: '取消' })).toBeInTheDocument()
    await user.type(within(card).getByLabelText('邮箱地址'), FIXTURE_MAILBOX)
    await user.type(within(card).getByLabelText('客户端授权码'), 'cancelled-authorization-code')
    await user.click(within(card).getByRole('button', { name: '取消' }))
    expect(within(card).getByRole('button', { name: '恢复' })).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: '重新授权' }))
    expect(within(card).getByLabelText('邮箱地址')).toHaveValue('')
    expect(within(card).getByLabelText('客户端授权码')).toHaveValue('')
  })

  it('连接 QQ 时使用 password 输入，提交后不在内存表单中保留邮箱或授权码', async () => {
    const fetchMock = setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts/qq/connect' && init?.method === 'POST') {
        return jsonBody({ operation_id: 'op-qq-1', status: 'pending' }, 202)
      }
    })
    const user = userEvent.setup()
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const qqCard = await screen.findByRole('article', { name: 'QQ 邮箱' })
    const address = within(qqCard).getByLabelText('邮箱地址')
    const authorizationCode = within(qqCard).getByLabelText('客户端授权码')
    expect(authorizationCode).toHaveAttribute('type', 'password')

    await user.type(address, FIXTURE_MAILBOX)
    await user.type(authorizationCode, 'fixture-authorization-code')
    await user.selectOptions(within(qqCard).getByLabelText('首次读取范围'), 'last_30_days')
    await user.click(within(qqCard).getByRole('button', { name: '连接邮箱' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/mail/accounts/qq/connect',
      expect.objectContaining({ method: 'POST' }),
    ))
    const connectCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/mail/accounts/qq/connect')
    expect(JSON.parse(String(connectCall?.[1]?.body))).toEqual({
      mailbox_address: FIXTURE_MAILBOX,
      authorization_code: 'fixture-authorization-code',
      history_window: 'last_30_days',
    })
    expect(screen.queryByDisplayValue(FIXTURE_MAILBOX)).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('fixture-authorization-code')).not.toBeInTheDocument()
    expect(within(qqCard).getByText('正在完成连接…')).toBeInTheDocument()
  })

  it('只展示结构化候选；补齐面试轮次和日期后确认写入', async () => {
    const rawMarker = 'RAW-SUBJECT-BODY-MUST-NOT-RENDER'
    const candidate = { ...pendingCandidate(), subject: rawMarker, body: rawMarker }
    const fetchMock = setupFetch([candidate], (url, init) => {
      if (url === '/api/mail/candidates/9/confirm' && init?.method === 'POST') {
        return jsonBody({ candidate: { ...candidate, state: 'committed' }, application: makeRecord({ id: 44 }), event: { id: 12 } })
      }
    })
    const onEventCommitted = vi.fn()
    const user = userEvent.setup()
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={onEventCommitted} />)

    const card = await screen.findByRole('article', { name: /示例科技.*后端工程师/ })
    expect(card).toHaveTextContent('面试（轮次待确认）')
    expect(card).toHaveTextContent('83%')
    expect(screen.queryByText(rawMarker)).not.toBeInTheDocument()

    const submit = within(card).getByRole('button', { name: '确认写入时间线' })
    expect(submit).toBeDisabled()
    await user.selectOptions(within(card).getByLabelText('确认阶段'), 'interview_2')
    await user.type(within(card).getByLabelText('面试日期'), '2026-09-03')
    expect(submit).toBeEnabled()
    await user.click(submit)

    await waitFor(() => expect(onEventCommitted).toHaveBeenCalledTimes(1))
    const confirmCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/mail/candidates/9/confirm')
    expect(JSON.parse(String(confirmCall?.[1]?.body))).toEqual({
      application_id: 44,
      stage: 'interview_2',
      scheduled_date: '2026-09-03',
      scheduled_time: null,
      deadline_date: null,
      deadline_time: null,
      timezone: 'Asia/Shanghai',
      confirm_personally_submitted: false,
    })
    expect(screen.queryByRole('article', { name: /示例科技.*后端工程师/ })).not.toBeInTheDocument()
  })

  it('邮件识别的“已投递”必须本人确认后才能写入', async () => {
    const candidate = pendingCandidate({ proposed_stage: 'applied', review_reasons: ['manual_stage'] })
    setupFetch([candidate], (url, init) => {
      if (url === '/api/mail/candidates/9/confirm' && init?.method === 'POST') {
        return jsonBody({ candidate: { ...candidate, state: 'committed' }, application: makeRecord({ id: 44 }), event: { id: 13 } })
      }
    })
    const user = userEvent.setup()
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const card = await screen.findByRole('article', { name: /示例科技.*后端工程师/ })
    const submit = within(card).getByRole('button', { name: '确认写入时间线' })
    expect(submit).toBeDisabled()
    await user.click(within(card).getByLabelText('我确认已亲自完成最终投递'))
    expect(submit).toBeEnabled()
  })

  it('切换到结束阶段时不提交先前识别出的计划日期', async () => {
    const candidate = pendingCandidate({
      proposed_stage: 'assessment',
      scheduled_date: '2026-09-03',
      scheduled_time: '10:30',
      deadline_date: '2026-09-05',
      deadline_time: '18:00',
      review_reasons: ['manual_stage'],
    })
    const fetchMock = setupFetch([candidate], (url, init) => {
      if (url === '/api/mail/candidates/9/confirm' && init?.method === 'POST') {
        return jsonBody({ candidate: { ...candidate, state: 'committed' }, application: makeRecord({ id: 44 }), event: { id: 14 } })
      }
    })
    const user = userEvent.setup()
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const card = await screen.findByRole('article', { name: /示例科技.*后端工程师/ })
    await user.selectOptions(within(card).getByLabelText('确认阶段'), 'offer')
    await user.click(within(card).getByRole('button', { name: '确认写入时间线' }))

    const confirmCall = await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url) === '/api/mail/candidates/9/confirm')
      expect(call).toBeDefined()
      return call
    })
    expect(JSON.parse(String(confirmCall?.[1]?.body))).toMatchObject({
      stage: 'offer',
      scheduled_date: null,
      scheduled_time: null,
      deadline_date: null,
      deadline_time: null,
    })
  })

  it('不把 00:00 当作未知时间写入', async () => {
    const candidate = pendingCandidate({ proposed_stage: 'interview_1', scheduled_date: '2026-09-03' })
    setupFetch([candidate])
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const card = await screen.findByRole('article', { name: /示例科技.*后端工程师/ })
    const timeInput = within(card).getByLabelText('计划时间（可选）')
    fireEvent.change(timeInput, { target: { value: '00:00' } })
    expect(within(card).getByText(/不能使用 00:00/)).toBeInTheDocument()
    expect(timeInput).toHaveAttribute('aria-invalid', 'true')
    expect(document.getElementById(timeInput.getAttribute('aria-describedby') || '')).toHaveTextContent(/不能使用 00:00/)
    expect(within(card).getByRole('button', { name: '确认写入时间线' })).toBeDisabled()
  })

  it('没有对应日期的残留 00:00 不阻塞确认，也不会提交该时间', async () => {
    const candidate = pendingCandidate({
      proposed_stage: 'assessment',
      scheduled_date: null,
      scheduled_time: '00:00',
      deadline_date: '2026-09-05',
    })
    const fetchMock = setupFetch([candidate], (url, init) => {
      if (url === '/api/mail/candidates/9/confirm' && init?.method === 'POST') {
        return jsonBody({ candidate: { ...candidate, state: 'committed' }, application: makeRecord({ id: 44 }), event: { id: 15 } })
      }
    })
    const user = userEvent.setup()
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const card = await screen.findByRole('article', { name: /示例科技.*后端工程师/ })
    const submit = within(card).getByRole('button', { name: '确认写入时间线' })
    expect(submit).toBeEnabled()
    await user.click(submit)

    const call = await waitFor(() => {
      const match = fetchMock.mock.calls.find(([url]) => String(url) === '/api/mail/candidates/9/confirm')
      expect(match).toBeDefined()
      return match
    })
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      scheduled_date: null,
      scheduled_time: null,
      deadline_date: '2026-09-05',
    })
  })

  it('刷新进入 connecting 状态时自动恢复账户状态检查', async () => {
    vi.useFakeTimers()
    let accountReads = 0
    const fetchMock = setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts' && init?.method === 'GET') {
        accountReads += 1
        const status = accountReads === 1 ? 'connecting' as const : 'connected' as const
        const accounts = disconnectedAccounts.map((account) => account.provider === 'outlook'
          ? { ...account, status, masked_address: 'f***@o***.com' }
          : account)
        return jsonBody({ items: accounts, pending_count: 0 })
      }
    })
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)
    await act(async () => {
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    expect(screen.getByText('连接中')).toBeInTheDocument()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_500)
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    expect(accountReads).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('已连接')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalled()
  })

  it('operation 404 后停止高频轮询并刷新账户状态', async () => {
    vi.useFakeTimers()
    let accountReads = 0
    let operationReads = 0
    const fetchMock = setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts' && init?.method === 'GET') {
        accountReads += 1
        const accounts = disconnectedAccounts.map((account) => account.provider === 'outlook'
          ? { ...account, status: 'connected' as const, masked_address: 'f***@o***.com' }
          : account)
        return jsonBody({ items: accounts, pending_count: 0 })
      }
      if (url === '/api/mail/accounts/outlook/sync' && init?.method === 'POST') {
        return jsonBody({ operation_id: 'missing-operation', status: 'pending' }, 202)
      }
      if (url === '/api/mail/operations/missing-operation' && init?.method === 'GET') {
        operationReads += 1
        return jsonBody({ code: 'mail_operation_not_found', message: 'fixture missing' }, 404)
      }
    })
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)
    await act(async () => {
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    fireEvent.click(screen.getByRole('button', { name: '立即同步' }))
    await act(async () => {
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500)
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    expect(operationReads).toBe(1)
    expect(accountReads).toBeGreaterThanOrEqual(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    expect(operationReads).toBe(1)
    expect(fetchMock).toHaveBeenCalled()
  })

  it('operation 状态连续网络失败三次后停止轮询', async () => {
    vi.useFakeTimers()
    let accountReads = 0
    let operationReads = 0
    setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts' && init?.method === 'GET') {
        accountReads += 1
        const accounts = disconnectedAccounts.map((account) => account.provider === 'outlook'
          ? { ...account, status: 'connected' as const, masked_address: 'f***@o***.com' }
          : account)
        return jsonBody({ items: accounts, pending_count: 0 })
      }
      if (url === '/api/mail/accounts/outlook/sync' && init?.method === 'POST') {
        return jsonBody({ operation_id: 'network-failure-operation', status: 'pending' }, 202)
      }
      if (url === '/api/mail/operations/network-failure-operation' && init?.method === 'GET') {
        operationReads += 1
        return Promise.reject(new TypeError('fixture network failure'))
      }
    })
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)
    await act(async () => {
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    fireEvent.click(screen.getByRole('button', { name: '立即同步' }))
    await act(async () => {
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })

    for (let attempt = 0; attempt < 3; attempt += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_500)
        for (let index = 0; index < 8; index += 1) await Promise.resolve()
      })
    }
    expect(operationReads).toBe(3)
    expect(accountReads).toBeGreaterThanOrEqual(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000)
      for (let index = 0; index < 8; index += 1) await Promise.resolve()
    })
    expect(operationReads).toBe(3)
  })

  it('断开账户后仍保留该提供商的待复核计数', async () => {
    let disconnected = false
    const fetchMock = setupFetch([], (url, init) => {
      if (url === '/api/mail/accounts' && init?.method === 'GET') {
        const accounts = disconnectedAccounts.map((account) => account.provider === 'qq'
          ? {
              ...account,
              status: disconnected ? 'disconnected' as const : 'connected' as const,
              masked_address: disconnected ? null : 'f***@q***.com',
              pending_count: 2,
            }
          : account)
        return jsonBody({ items: accounts, pending_count: 2 })
      }
      if (url === '/api/mail/accounts/qq' && init?.method === 'DELETE') {
        disconnected = true
        return new Response(null, { status: 204 })
      }
    })
    const user = userEvent.setup()
    render(<MailIngestionView onNotify={vi.fn()} onEventCommitted={vi.fn()} />)

    const card = await screen.findByRole('article', { name: 'QQ 邮箱' })
    expect(card).toHaveTextContent('2 条')
    await user.click(within(card).getByRole('button', { name: '重新授权' }))
    await user.type(within(card).getByLabelText('邮箱地址'), FIXTURE_MAILBOX)
    await user.type(within(card).getByLabelText('客户端授权码'), 'disconnect-authorization-code')
    await user.click(within(card).getByRole('button', { name: '断开' }))
    expect(screen.queryByDisplayValue(FIXTURE_MAILBOX)).not.toBeInTheDocument()
    expect(screen.queryByDisplayValue('disconnect-authorization-code')).not.toBeInTheDocument()
    await user.click(screen.getByTestId('confirm-dialog-confirm'))

    await waitFor(() => {
      expect(within(card).getByText('未连接')).toBeInTheDocument()
      expect(card).toHaveTextContent('2 条')
    })
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/mail/accounts/qq')).toBe(true)
  })
})
