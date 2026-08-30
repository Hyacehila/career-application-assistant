import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { ApplicationDetail } from './api/client'
import { makeEvent, makeRecord } from './test/fixtures'
import { jsonBody, okBody, STANDARD_HEALTH } from './test/http'
import type { BoardGroup } from './lib/statuses'

const record = makeRecord({ id: 1, company_name: '示例科技', job_title: '前端工程师' })

function listPayload() {
  return {
    items: [record],
    total: 1,
    page: 1,
    page_size: 20,
    counts: { pending_review: 1, applied: 0, assessment: 0, interview: 0, ended: 0 },
    options: { types: [], cities: [], sources: [] },
  }
}

function detailPayload(): ApplicationDetail {
  return {
    application: record,
    events: [makeEvent({ id: 5, stage: 'pending_review', event_date: '2026-08-20', source: 'agent_fill' })],
  }
}

const GROUP_ORDER: BoardGroup[] = ['pending_review', 'applied', 'assessment', 'interview', 'ended']

function layoutColumns() {
  GROUP_ORDER.forEach((group, index) => {
    const element = screen.getByTestId(`droppable-${group}`)
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
      left: index * 300,
      top: 0,
      width: 280,
      height: 120,
      right: index * 300 + 280,
      bottom: 120,
      x: index * 300,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect)
  })
}

async function dragTo(card: HTMLElement, group: BoardGroup) {
  layoutColumns()
  const target = screen.getByTestId(`droppable-${group}`)
  const rect = target.getBoundingClientRect()
  const targetCenter = {
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
  }
  const fire = async (fn: () => void) => {
    act(fn)
    await act(async () => {})
  }
  await fire(() => fireEvent.mouseDown(card, { clientX: 0, clientY: 0 }))
  await fire(() => fireEvent.mouseMove(card, { clientX: 10, clientY: 10 }))
  await fire(() => fireEvent.mouseMove(card, { clientX: targetCenter.x, clientY: targetCenter.y }))
  await fire(() => fireEvent.mouseUp(card, { clientX: targetCenter.x, clientY: targetCenter.y }))
  // dnd-kit 拖拽结束后约 50ms 内在 document 捕获阶段拦截 click（防止拖拽误触），
  // 等待其释放后再交互对话框，模拟真实用户节奏
  await new Promise((resolve) => setTimeout(resolve, 120))
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('App 核心交互', () => {
  it('写操作失败：显示带后端 message 的 Toast，卡片回滚到原列', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/health') return Promise.resolve(jsonBody(STANDARD_HEALTH))
      if (url.startsWith('/api/applications?') && init?.method === 'GET') {
        return Promise.resolve(jsonBody(listPayload()))
      }
      return Promise.resolve(jsonBody({ code: 'validation_error', message: '测评至少需要计划日期或截止日期' }, 422))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    const card = await screen.findByTestId('board-card-1')
    await dragTo(card, 'assessment')
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('计划日期')
    fireEvent.change(screen.getByTestId('status-form-scheduled-date'), { target: { value: '2026-09-01' } })
    await user.click(screen.getByTestId('status-form-submit'))
    // 错误同时出现在弹窗内联提示与 Toast 中
    const inline = await screen.findByTestId('status-form-error')
    expect(inline).toHaveTextContent('测评至少需要计划日期或截止日期')
    const toast = await screen.findByText((text, element) =>
      text.includes('测评至少需要计划日期或截止日期') && String(element?.className ?? '').includes('toastCard'),
    )
    expect(toast).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '取消' }))
    await vi.waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })
    expect(screen.getByRole('region', { name: '待确认投递' })).toHaveTextContent('示例科技')
    expect(screen.getByRole('region', { name: '笔试 / 测评' })).not.toHaveTextContent('示例科技')
  })

  it('拖拽到“已投递”：确认对话框确认后调用 postEvent(applied) 并刷新列表', async () => {
    let listCalls = 0
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/health') return Promise.resolve(jsonBody(STANDARD_HEALTH))
      if (url.startsWith('/api/applications?') && init?.method === 'GET') {
        listCalls += 1
        return Promise.resolve(jsonBody(listPayload()))
      }
      if (url === '/api/applications/1/events' && init?.method === 'POST') {
        return Promise.resolve(okBody({ id: 99, stage: 'applied', event_date: '2026-08-28', source: 'user_confirmation' }))
      }
      return Promise.resolve(jsonBody({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    const card = await screen.findByTestId('board-card-1')
    await dragTo(card, 'applied')
    const confirmButton = await screen.findByRole('button', { name: '确认' })
    expect(screen.getByText('确认已手动完成最终提交？', { exact: false })).toBeInTheDocument()
    await user.click(confirmButton)
    const eventCall = await vi
      .waitFor(
        () => {
          const call = fetchMock.mock.calls.find(
            ([url, init]) => String(url) === '/api/applications/1/events' && init?.method === 'POST',
          )
          if (!call) throw new Error('postEvent 尚未调用')
          return call
        },
        { timeout: 5000 },
      )
      .then((call) => call as [string, RequestInit])
    expect(JSON.parse(String(eventCall[1].body))).toMatchObject({
      stage: 'applied',
      source: 'user_confirmation',
    })
    expect(JSON.parse(String(eventCall[1].body)).event_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(await screen.findByText('已标记为已投递')).toBeInTheDocument()
    expect(listCalls).toBeGreaterThanOrEqual(2)
  })

  it('新增记录成功：短 Toast + 列表 refetch', async () => {
    let listCalls = 0
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/health') return Promise.resolve(jsonBody(STANDARD_HEALTH))
      if (url.startsWith('/api/applications?') && init?.method === 'GET') {
        listCalls += 1
        return Promise.resolve(jsonBody(listPayload()))
      }
      if (url === '/api/applications' && init?.method === 'POST') {
        return Promise.resolve(okBody(makeRecord({ id: 2, company_name: '示例网络' })))
      }
      return Promise.resolve(jsonBody({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByTestId('new-record-button'))
    await screen.findByTestId('record-form-company')
    await user.type(screen.getByTestId('record-form-company'), '示例网络')
    await user.type(screen.getByTestId('record-form-job'), '后端工程师')
    await user.click(screen.getByTestId('record-form-submit'))
    expect(await screen.findByText('记录已创建')).toBeInTheDocument()
    expect(listCalls).toBeGreaterThanOrEqual(2)
    const postCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/applications' && init?.method === 'POST')
    expect(postCall).toBeTruthy()
    expect(JSON.parse(String((postCall as unknown as [string, RequestInit])[1].body))).toMatchObject({
      company_name: '示例网络',
      job_title: '后端工程师',
    })
  })

  it('点击卡片打开详情抽屉，ESC 关闭抽屉', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/health') return Promise.resolve(jsonBody(STANDARD_HEALTH))
      if (url.startsWith('/api/applications?') && init?.method === 'GET') {
        return Promise.resolve(jsonBody(listPayload()))
      }
      if (url === '/api/applications/1' && init?.method === 'GET') {
        return Promise.resolve(jsonBody(detailPayload()))
      }
      return Promise.resolve(jsonBody({}))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    const card = await screen.findByTestId('board-card-1')
    await user.click(card)
    const status = await screen.findByTestId('drawer-current-status')
    expect(status).toHaveTextContent('待确认投递')
    await act(async () => {
      fireEvent.keyDown(document, { key: 'Escape' })
      await new Promise((resolve) => setTimeout(resolve, 240))
    })
    await vi.waitFor(() => {
      expect(screen.queryByTestId('detail-drawer')).not.toBeInTheDocument()
    })
  })
})
