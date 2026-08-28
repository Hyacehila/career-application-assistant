import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { jsonBody } from './test/http'
import { makeRecord } from './test/fixtures'

function listPayload() {
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: 20,
    counts: { pending_review: 0, applied: 0, assessment: 0, interview: 0, ended: 0 },
    options: { types: [], cities: [], sources: [] },
  }
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
    const fetchMock = vi.fn().mockResolvedValue(jsonBody(listPayload()))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    expect(screen.getByText('投递看板')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '看板' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '表格' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索公司或岗位')).toBeInTheDocument()
    expect(screen.getByTestId('new-record-button')).toBeInTheDocument()
    expect(await screen.findByText('暂无投递记录')).toBeInTheDocument()
  })

  it('切换视图更新 URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonBody(listPayload()))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: '表格' }))
    expect(window.location.search).toBe('?view=table')
    await user.click(screen.getByRole('button', { name: '看板' }))
    expect(window.location.search).toBe('')
  })

  it('搜索输入防抖 300ms 后写入 URL', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue(jsonBody(listPayload()))
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
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('network down'))
      .mockResolvedValueOnce(jsonBody(listPayload()))
      .mockResolvedValueOnce(jsonBody(listPayload()))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    expect(await screen.findByText('加载失败')).toBeInTheDocument()
    expect(screen.getByTestId('error-retry')).toBeInTheDocument()
    await user.click(screen.getByTestId('error-retry'))
    expect(await screen.findByText('暂无投递记录')).toBeInTheDocument()
  })

  it('看板请求完整过滤集并显示超过 20 条的跨阶段记录', async () => {
    const items = [
      ...Array.from({ length: 21 }, (_, index) =>
        makeRecord({ id: index + 1, company_name: `示例公司 ${String(index + 1).padStart(2, '0')}` }),
      ),
      makeRecord({ id: 22, company_name: '独立面试示例', current_status: 'interview_1' }),
      makeRecord({ id: 23, company_name: '独立结束示例', current_status: 'offer' }),
    ]
    const fetchMock = vi.fn().mockResolvedValue(jsonBody({
      items,
      total: items.length,
      page: 1,
      page_size: 100,
      counts: { pending_review: 21, applied: 0, assessment: 0, interview: 1, ended: 1 },
      options: { types: [], cities: [], sources: [] },
    }))
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    expect(await screen.findByText('独立面试示例')).toBeInTheDocument()
    expect(screen.getByText('独立结束示例')).toBeInTheDocument()
    expect(screen.getAllByTestId(/^board-card-\d+$/)).toHaveLength(23)
    expect(String(fetchMock.mock.calls[0][0])).toContain('page_size=100')
  })
})
