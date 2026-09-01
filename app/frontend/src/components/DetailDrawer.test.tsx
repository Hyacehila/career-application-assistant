import { render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplicationRecord, ApplicationDetail } from '../api/client'
import { makeEvent, makeRecord } from '../test/fixtures'
import { jsonBody, okBody } from '../test/http'
import DetailDrawer from './DetailDrawer'

function detailFixture(record: ApplicationRecord): ApplicationDetail {
  return {
    application: record,
    events: [
      makeEvent({ id: 30, stage: 'interview_1', event_date: '2026-08-25', scheduled_date: '2026-08-28', scheduled_time: '14:00', mode: 'online', location: '腾讯会议', note: '一面（技术）', source: 'email_extract', created_at: '2026-08-25T09:00:00+08:00' }),
      makeEvent({ id: 20, stage: 'assessment', event_date: '2026-08-22', deadline_date: '2026-08-27', source: 'manual_ui', created_at: '2026-08-22T09:00:00+08:00' }),
      makeEvent({ id: 10, stage: 'applied', event_date: '2026-08-20', source: 'user_confirmation', created_at: '2026-08-20T09:00:00+08:00' }),
    ],
  }
}

function stubFetch() {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const path = String(input)
    if (path.includes('/events') || path.includes('DELETE')) return Promise.resolve(okBody({}))
    return Promise.resolve(jsonBody(detailFixture(record)))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const record = makeRecord({
  id: 42,
  company_name: '示例科技',
  job_title: '前端工程师',
  department: '基础设施部',
  job_code: 'FE-2026-001',
  application_type: '社招',
  location: '上海',
  source: '官方网站',
  job_url: 'https://example.com/career/frontend',
  current_status: 'interview_1',
  submitted_at: '2026-08-20T10:00:00+08:00',
  next_action: '准备一面：手写代码与项目深挖',
  next_action_date: '2026-08-28',
})

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DetailDrawer', () => {
  it('共享弹窗层级高于详情抽屉，编辑和状态表单不会被遮挡', () => {
    const tokens = readFileSync(path.join(process.cwd(), 'src/styles/tokens.css'), 'utf8')
    const drawer = readFileSync(path.join(process.cwd(), 'src/components/DetailDrawer.module.css'), 'utf8')
    const overlayZ = Number(tokens.match(/\.overlayLayer\s*\{[^}]*z-index:\s*(\d+)/s)?.[1])
    const drawerZ = Number(drawer.match(/\.drawerWrap\s*\{[^}]*z-index:\s*(\d+)/s)?.[1])
    expect(overlayZ).toBeGreaterThan(drawerZ)
  })
  it('拉取详情后显示时间线、当前事件高亮与下一步', async () => {
    stubFetch()
    render(
      <DetailDrawer
        recordId={42}
        record={record}
        onClose={() => {}}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId('drawer-current-status')).toHaveTextContent('1面')
    })
    const timeline = screen.getByText('进度时间线').parentElement
    expect(timeline).toBeInTheDocument()
    expect(screen.getByText('一面（技术）')).toBeInTheDocument()
    expect(screen.getByText(/计划 2026-08-28 14:00/)).toBeInTheDocument()
    expect(screen.getByText(/截止 2026-08-27/)).toBeInTheDocument()
    const current = screen.getByTestId('timeline-current')
    expect(current).toHaveTextContent('1面')
    expect(current).toHaveTextContent('2026-08-25')
    expect(screen.getByTestId('drawer-next-action')).toHaveTextContent('准备一面：手写代码与项目深挖')
    expect(screen.getByTestId('drawer-next-action')).toHaveTextContent('计划日期 2026-08-28')
    expect(screen.getByText('基础设施部')).toBeInTheDocument()
    expect(screen.getByText('FE-2026-001')).toBeInTheDocument()
    expect(screen.getByText('记录 #42')).toBeInTheDocument()
  })

  it('当前为精确面试轮次时，从详情打开独立完成弹窗', async () => {
    stubFetch()
    const user = userEvent.setup()
    render(
      <DetailDrawer
        recordId={42}
        record={record}
        onClose={() => {}}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    )
    const completionButton = await screen.findByTestId('drawer-completion-button')
    expect(completionButton).toHaveTextContent('标记本轮已结束')
    await user.click(completionButton)
    expect(screen.getByRole('dialog', { name: '标记1面已结束' })).toBeInTheDocument()
    expect(screen.getByText(/完成状态不会自动推进到下一阶段/)).toBeInTheDocument()
  })

  it.each([
    { status: 'applied', label: '投递于 2026-08-17', timelineLabel: '已投递', source: 'user_confirmation' },
    { status: 'offer', label: '结束于 2026-08-17', timelineLabel: 'Offer', source: 'manual_ui' },
  ] as const)('$label 记录保留历史 pending_review 节点，并统一显示为待确认投递', async ({ status, label, timelineLabel, source }) => {
    const progressedRecord = makeRecord({
      id: 43,
      company_name: '示例网络',
      job_title: '后端工程师',
      current_status: status,
      submitted_at: '2026-08-17T10:00:00+08:00',
    })
    const detail: ApplicationDetail = {
      application: progressedRecord,
      events: [
        makeEvent({ id: 21, stage: status, event_date: '2026-08-17', source, created_at: '2026-08-30T13:01:00+08:00' }),
        makeEvent({ id: 20, stage: 'pending_review', event_date: '2026-08-30', source: 'agent_fill', created_at: '2026-08-30T13:00:00+08:00' }),
      ],
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonBody(detail)))

    render(
      <DetailDrawer
        recordId={43}
        record={progressedRecord}
        onClose={() => {}}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('drawer-current-status')).toHaveTextContent(label)
    })
    expect(screen.getByTestId('timeline-current')).toHaveTextContent(timelineLabel)
    expect(screen.getByText('待确认投递')).toBeInTheDocument()
    expect(screen.queryByText('待人工复核')).not.toBeInTheDocument()
    expect(screen.getByText('2026-08-30')).toBeInTheDocument()
  })

  it('更多操作 → 软删除确认后调用 deleteApplication 并关闭抽屉', async () => {
    const fetchMock = stubFetch()
    const onDeleted = vi.fn()
    const user = userEvent.setup()
    const { unmount } = render(
      <DetailDrawer
        recordId={42}
        record={record}
        onClose={() => {}}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={onDeleted}
        onError={() => {}}
      />,
    )
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '更多操作' })).toBeInTheDocument()
    })
    const moreButton = screen.getByRole('button', { name: '更多操作' })
    await user.click(moreButton)
    await screen.findByTestId('drawer-more-menu')
    await user.click(screen.getByTestId('drawer-delete-button'))
    expect(screen.getByTestId('drawer-delete-confirm')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => {
      expect(onDeleted).toHaveBeenCalledWith(42)
    })
    const deleteCall = fetchMock.mock.calls.find(([url, init]) => String(url) === '/api/applications/42' && init?.method === 'DELETE')
    expect(deleteCall).toBeTruthy()
    unmount()
  })

  it('reduced-motion 时抽屉无 transition', async () => {
    const matchMediaMock = vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
    Object.defineProperty(window, 'matchMedia', { value: matchMediaMock, writable: true })
    stubFetch()
    const { container } = render(
      <DetailDrawer
        recordId={42}
        record={record}
        onClose={() => {}}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    )
    await waitFor(() => {
      const drawer = container.querySelector('[role="dialog"]')
      expect(drawer).not.toBeNull()
    })
    const drawer = container.querySelector('[role="dialog"]') as HTMLElement
    expect(drawer.style.transition).toBe('none')
  })

  it('遮罩点击触发 onClose', async () => {
    stubFetch()
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <DetailDrawer
        recordId={42}
        record={record}
        onClose={onClose}
        onUpdateStatus={() => {}}
        onEdit={() => {}}
        onDeleted={() => {}}
        onError={() => {}}
      />,
    )
    await waitFor(() => {
      expect(screen.getByTestId('detail-drawer-backdrop')).toBeInTheDocument()
    })
    await user.click(screen.getByTestId('detail-drawer-backdrop'))
    expect(onClose).toHaveBeenCalled()
  })
})
