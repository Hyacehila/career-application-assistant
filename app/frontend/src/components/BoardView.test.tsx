import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BoardGroup } from '../lib/statuses'
import { makeRecord } from '../test/fixtures'
import { okBody } from '../test/http'
import BoardView from './BoardView'
import StatusFormDialog from './StatusFormDialog'
import { useState } from 'react'
import type { ApplicationRecord } from '../api/client'

const baseCounts = {
  pending_review: 0,
  applied: 0,
  assessment: 0,
  interview: 0,
  ended: 0,
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  document.body.innerHTML = ''
})

const GROUP_ORDER: BoardGroup[] = ['pending_review', 'applied', 'assessment', 'interview', 'ended']

function layoutColumns() {
  GROUP_ORDER.forEach((group, index) => {
    const element = screen.getByTestId(`droppable-${group}`)
    vi.spyOn(element, 'getBoundingClientRect').mockReturnValue({
      left: index * 300,
      top: 0,
      width: 280,
      height: 180,
      right: index * 300 + 280,
      bottom: 180,
      x: index * 300,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect)
  })
}

async function dragToGroup(card: HTMLElement, group: BoardGroup) {
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
}

describe('BoardView', () => {
  it('渲染五个固定顺序的阶段列与计数', () => {
    render(
      <BoardView
        items={[makeRecord({ id: 1, current_status: 'applied' })]}
        loading={false}
        error={null}
        counts={{ ...baseCounts, applied: 1 }}
        stageGroup=""
        selectedId={null}
        onOpen={() => {}}
        onNewRecord={() => {}}
        onRetry={() => {}}
        onStatusChange={() => {}}
      />,
    )
    const labels = ['待确认投递', '已投递', '笔试 / 测评', '面试', '已结束']
    labels.forEach((label) => {
      expect(screen.getByRole('region', { name: label })).toBeInTheDocument()
    })
    const pendingColumn = screen.getByRole('region', { name: '待确认投递' })
    expect(pendingColumn).toHaveTextContent('待确认投递')
    expect(pendingColumn).toHaveTextContent('0')
    expect(pendingColumn).toHaveTextContent('暂无记录')
    expect(screen.getAllByText('暂无记录').length).toBe(4)
  })

  it('按 current_status 正确分组，并让所有阶段卡片只显示公司名和岗位名', () => {
    const records = [
      makeRecord({ id: 1, company_name: '示例科技', job_title: '前端工程师', current_status: 'pending_review' }),
      makeRecord({ id: 2, company_name: '示例网络', job_title: '后端工程师', current_status: 'applied' }),
      makeRecord({ id: 3, company_name: '示例云', job_title: '算法工程师', current_status: 'interview_1' }),
      makeRecord({ id: 4, company_name: '示例数据', job_title: '数据工程师', current_status: 'offer' }),
      makeRecord({ id: 5, company_name: '示例安全', job_title: '安全工程师', current_status: 'assessment', next_action_date: '2026-09-01' }),
    ]
    render(
      <BoardView
        items={records}
        loading={false}
        error={null}
        counts={{ pending_review: 1, applied: 1, assessment: 1, interview: 1, ended: 1 }}
        stageGroup=""
        selectedId={null}
        onOpen={() => {}}
        onNewRecord={() => {}}
        onRetry={() => {}}
        onStatusChange={() => {}}
      />,
    )
    expect(screen.getByRole('region', { name: '待确认投递' })).toHaveTextContent('示例科技')
    expect(screen.getByRole('region', { name: '已投递' })).toHaveTextContent('示例网络')
    expect(screen.getByRole('region', { name: '面试' })).toHaveTextContent('示例云')
    expect(screen.getByRole('region', { name: '已结束' })).toHaveTextContent('示例数据')
    expect(screen.getByRole('region', { name: '笔试 / 测评' })).toHaveTextContent('示例安全')

    for (const record of records) {
      const card = screen.getByTestId(`board-card-${record.id}`)
      expect(card).toHaveTextContent(record.company_name)
      expect(card).toHaveTextContent(record.job_title)
      expect(card).toHaveAttribute('aria-label', `${record.company_name} ${record.job_title}`)
      expect(card).toHaveAttribute('title', `${record.company_name} · ${record.job_title}`)
      expect(within(card).queryByText('公司', { exact: true })).not.toBeInTheDocument()
      expect(within(card).queryByText('岗位', { exact: true })).not.toBeInTheDocument()
      expect(card).not.toHaveTextContent('上海')
      expect(card).not.toHaveTextContent('校招')
      expect(card).not.toHaveTextContent('官方网站')
      expect(card).not.toHaveTextContent('更新')
      expect(screen.queryByTestId(`board-card-highlight-${record.id}`)).not.toBeInTheDocument()
    }
    expect(screen.getByTestId('board-card-3')).not.toHaveTextContent('1面')
    expect(screen.getByTestId('board-card-4')).not.toHaveTextContent('Offer')
    expect(screen.getByTestId('board-card-5')).not.toHaveTextContent('计划')
  })

  it('空数据库时整板显示 EmptyState', () => {
    render(
      <BoardView
        items={[]}
        loading={false}
        error={null}
        counts={baseCounts}
        stageGroup=""
        selectedId={null}
        onOpen={() => {}}
        onNewRecord={() => {}}
        onRetry={() => {}}
        onStatusChange={() => {}}
        onEmptyNewRecord={() => {}}
      />,
    )
    expect(screen.getByText('还没有申请记录')).toBeInTheDocument()
  })

  it('拖拽到“已投递”触发 onStatusChange 回调（参数为当前记录与目标分组）', async () => {
    const record = makeRecord({ id: 7, company_name: '示例科技' })
    const onStatusChange = vi.fn()
    const onOpen = vi.fn()
    render(
      <BoardView
        items={[record]}
        loading={false}
        error={null}
        counts={{ ...baseCounts, pending_review: 1 }}
        stageGroup=""
        selectedId={null}
        onOpen={onOpen}
        onNewRecord={() => {}}
        onRetry={() => {}}
        onStatusChange={onStatusChange}
      />,
    )
    const card = screen.getByTestId('board-card-7')
    await dragToGroup(card, 'applied')
    await waitFor(() => {
      expect(onStatusChange).toHaveBeenCalledTimes(1)
      expect(onStatusChange).toHaveBeenCalledWith(record, 'applied')
    })
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('拖拽到“面试”打开面试表单，显示轮次与必填日期', async () => {
    const record = makeRecord({ id: 8, company_name: '示例科技' })
    const onStatusChange = vi.fn()
    const Harness = () => {
      const [target, setTarget] = useState<ApplicationRecord | null>(null)
      return (
        <>
          <BoardView
            items={[record]}
            loading={false}
            error={null}
            counts={{ ...baseCounts, pending_review: 1 }}
            stageGroup=""
            selectedId={null}
            onOpen={() => {}}
            onNewRecord={() => {}}
            onRetry={() => {}}
            onStatusChange={(rec, group) => {
              onStatusChange(rec, group)
              if (group === 'interview') setTarget(rec)
            }}
          />
          {target && <StatusFormDialog target="interview" record={target} onClose={() => setTarget(null)} />}
        </>
      )
    }
    render(<Harness />)
    const card = screen.getByTestId('board-card-8')
    await dragToGroup(card, 'interview')
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('面试轮次')
    expect(dialog).toHaveTextContent('1面')
    expect(dialog).toHaveTextContent('HR面')
    expect(screen.getByTestId('status-form-scheduled-date')).toBeInTheDocument()
    expect(onStatusChange).toHaveBeenCalledWith(record, 'interview')
  })

  it.each([
    ['Space', ' ', 'Space'],
    ['Enter', 'Enter', 'Enter'],
  ])('键盘传感器可用 Space 启动并用 %s 落下卡片', async (_label, dropKey, dropCode) => {
    const record = makeRecord({ id: 9, company_name: '示例科技' })
    const onStatusChange = vi.fn()
    const onOpen = vi.fn()
    render(
      <BoardView
        items={[record]}
        loading={false}
        error={null}
        counts={{ ...baseCounts, pending_review: 1 }}
        stageGroup=""
        selectedId={null}
        onOpen={onOpen}
        onNewRecord={() => {}}
        onRetry={() => {}}
        onStatusChange={onStatusChange}
      />,
    )
    const card = screen.getByTestId('board-card-9')
    expect(card).toHaveAttribute('role', 'button')
    expect(card).toHaveAttribute('aria-roledescription', 'draggable')
    layoutColumns()
    vi.spyOn(card, 'getBoundingClientRect').mockReturnValue({
      left: 4,
      top: 40,
      width: 272,
      height: 72,
      right: 276,
      bottom: 112,
      x: 4,
      y: 40,
      toJSON: () => ({}),
    } as DOMRect)
    card.focus()
    await act(async () => {
      fireEvent.keyDown(card, { key: ' ', code: 'Space' })
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    for (let step = 0; step < 12; step += 1) {
      await act(async () => {
        fireEvent.keyDown(document, { key: 'ArrowRight', code: 'ArrowRight' })
      })
    }
    await act(async () => {
      fireEvent.keyDown(document, { key: dropKey, code: dropCode })
    })
    await waitFor(() => {
      expect(onStatusChange).toHaveBeenCalledWith(record, 'applied')
    })
    expect(onOpen).not.toHaveBeenCalled()
  })

  it('Enter 只打开详情，不启动键盘拖拽', () => {
    const record = makeRecord({ id: 10, company_name: '示例网络' })
    const onOpen = vi.fn()
    const onStatusChange = vi.fn()
    render(
      <BoardView
        items={[record]}
        loading={false}
        error={null}
        counts={{ ...baseCounts, pending_review: 1 }}
        stageGroup=""
        selectedId={null}
        onOpen={onOpen}
        onNewRecord={() => {}}
        onRetry={() => {}}
        onStatusChange={onStatusChange}
      />,
    )

    const card = screen.getByTestId('board-card-10')
    card.focus()
    fireEvent.keyDown(card, { key: 'Enter', code: 'Enter' })
    expect(onOpen).toHaveBeenCalledWith(10)
    expect(onStatusChange).not.toHaveBeenCalled()
  })
})
