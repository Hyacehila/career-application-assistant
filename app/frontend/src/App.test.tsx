import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { ListApplicationsResponse } from './api/client'
import { DEMO_HEALTH, jsonBody, STANDARD_HEALTH } from './test/http'
import { makeRecord } from './test/fixtures'

function listPayload(): ListApplicationsResponse {
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
    counts: { pending_review: 0, applied: 0, assessment: 0, interview: 0, ended: 0 },
    options: { types: [], cities: [], sources: [] },
  }
}

function standardFetch(payload = listPayload()) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url === '/api/health') return Promise.resolve(jsonBody(STANDARD_HEALTH))
    if (url.startsWith('/api/applications?')) return Promise.resolve(jsonBody(payload))
    throw new Error(`unexpected request: ${url}`)
  })
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('App 壳', () => {
  it('显示产品名、视图切换、搜索框与新增记录按钮', async () => {
    const fetchMock = standardFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    expect(screen.getByText('求职投递助手')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '看板' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '表格' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索公司或岗位')).toBeInTheDocument()
    expect(screen.getByTestId('new-record-button')).toBeInTheDocument()
    expect(await screen.findByText('还没有申请记录')).toBeInTheDocument()
    expect(screen.getByText('用 Codex 将当前招聘表单准备到最终提交前，或手动新增记录。复核和正式提交始终由你本人完成。')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '邮箱接入' })).toBeInTheDocument()
    expect(screen.queryByTestId('demo-notice')).not.toBeInTheDocument()
  })

  it('切换视图更新 URL', async () => {
    const fetchMock = standardFetch()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: '表格' }))
    expect(window.location.search).toBe('?view=table')
    await user.click(screen.getByRole('button', { name: '看板' }))
    expect(window.location.search).toBe('')
  })

  it('邮箱接入是独立第三视图，并隐藏看板搜索、筛选和新增按钮', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/health') {
        return Promise.resolve(jsonBody(STANDARD_HEALTH))
      }
      if (url === '/api/mail/accounts') {
        return Promise.resolve(jsonBody({ items: [], pending_count: 0 }))
      }
      if (url === '/api/mail/candidates?state=pending') {
        return Promise.resolve(jsonBody({ items: [], total: 0 }))
      }
      if (url.startsWith('/api/applications?')) {
        return Promise.resolve(jsonBody(listPayload()))
      }
      throw new Error(`unexpected request: ${init?.method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: '邮箱接入' }))
    expect(window.location.search).toBe('?view=mail')
    expect(await screen.findByRole('heading', { name: '邮箱接入', level: 1 })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('搜索公司或岗位')).not.toBeInTheDocument()
    expect(screen.queryByTestId('new-record-button')).not.toBeInTheDocument()
  })

  it('搜索输入防抖 300ms 后写入 URL', async () => {
    vi.useFakeTimers()
    const fetchMock = standardFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await act(async () => {
      await Promise.resolve()
    })
    const input = screen.getByPlaceholderText('搜索公司或岗位')
    fireEvent.change(input, { target: { value: '示例科技' } })
    expect(window.location.search).toBe('')
    await act(async () => {
      vi.advanceTimersByTime(300)
    })
    expect(window.location.search).toBe(`?q=${encodeURIComponent('示例科技')}`)
  })

  it('API 失败显示错误状态，点击重试后恢复', async () => {
    let applicationCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/health') return Promise.resolve(jsonBody(STANDARD_HEALTH))
      if (url.startsWith('/api/applications?')) {
        applicationCalls += 1
        if (applicationCalls === 1) return Promise.reject(new TypeError('network down'))
        return Promise.resolve(jsonBody(listPayload()))
      }
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByText('加载失败')).toBeInTheDocument()
    expect(screen.getByTestId('error-retry')).toBeInTheDocument()
    await user.click(screen.getByTestId('error-retry'))
    expect(await screen.findByText('还没有申请记录')).toBeInTheDocument()
  })

  it('看板请求完整过滤集并显示超过 20 条的跨阶段记录', async () => {
    const items = [
      ...Array.from({ length: 21 }, (_, index) =>
        makeRecord({ id: index + 1, company_name: `示例公司 ${String(index + 1).padStart(2, '0')}` }),
      ),
      makeRecord({ id: 22, company_name: '独立面试示例', current_status: 'interview_1' }),
      makeRecord({ id: 23, company_name: '独立结束示例', current_status: 'offer' }),
    ]
    const fetchMock = standardFetch({
      items,
      total: items.length,
      page: 1,
      page_size: 100,
      counts: { pending_review: 21, applied: 0, assessment: 0, interview: 1, ended: 1 },
      options: { types: [], cities: [], sources: [] },
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByText('独立面试示例')).toBeInTheDocument()
    expect(screen.getByText('独立结束示例')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^board-card-\d+$/)).toHaveLength(23)
    const applicationCall = fetchMock.mock.calls.find(([url]) => String(url).startsWith('/api/applications?'))
    expect(String(applicationCall?.[0])).toContain('page_size=100')
  })

  it('health 与看板数据在首屏并行请求', async () => {
    let resolveHealth: ((response: Response) => void) | undefined
    let resolveApplications: ((response: Response) => void) | undefined
    const healthResponse = new Promise<Response>((resolve) => { resolveHealth = resolve })
    const applicationsResponse = new Promise<Response>((resolve) => { resolveApplications = resolve })
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/api/health') return healthResponse
      if (url.startsWith('/api/applications?')) return applicationsResponse
      throw new Error(`unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await vi.waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/health')).toBe(true)
      expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/applications?'))).toBe(true)
    })
    resolveHealth?.(jsonBody(STANDARD_HEALTH))
    resolveApplications?.(jsonBody(listPayload()))
    expect(await screen.findByText('还没有申请记录')).toBeInTheDocument()
  })

  it('Demo 隐藏邮箱、归一化 mail URL，并可重置后刷新六条合成记录', async () => {
    window.history.replaceState(null, '', '/?view=mail')
    const records = Array.from({ length: 6 }, (_, index) =>
      makeRecord({ id: index + 1, company_name: `虚构公司 ${index + 1}` }),
    )
    let listCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/health') return Promise.resolve(jsonBody(DEMO_HEALTH))
      if (url.startsWith('/api/applications?')) {
        listCalls += 1
        return Promise.resolve(jsonBody({
          items: records,
          total: 6,
          page: 1,
          page_size: 100,
          counts: { pending_review: 6, applied: 0, assessment: 0, interview: 0, ended: 0 },
          options: { types: [], cities: [], sources: [] },
        }))
      }
      if (url === '/api/demo/reset' && init?.method === 'POST') {
        return Promise.resolve(jsonBody({ ok: true, records_seeded: 6 }))
      }
      throw new Error(`unexpected request: ${init?.method} ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()

    render(<App />)

    expect(await screen.findByTestId('demo-notice')).toHaveTextContent('合成演示数据')
    await vi.waitFor(() => expect(window.location.search).toBe(''))
    expect(screen.queryByRole('button', { name: '邮箱接入' })).not.toBeInTheDocument()
    expect(await screen.findAllByTestId(/^board-card-\d+$/)).toHaveLength(6)

    await user.click(screen.getByTestId('demo-reset'))

    expect(await screen.findByText('演示数据已重置')).toBeInTheDocument()
    expect(listCalls).toBeGreaterThanOrEqual(2)
    const resetCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/demo/reset')
    expect(resetCall?.[1]).toMatchObject({ method: 'POST', body: '{}' })
  })
})
