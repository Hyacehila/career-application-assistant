import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
      height: 120,
      right: index * 300 + 280,
      bottom: 120,
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
        items={[makeRecord({ id: 1 })]}
        loading={false}
        error={null}
        counts={{ ...baseCounts, pending_review: 1 }}
        stageGroup=""
        selectedId={null}
        onOpen={() => {}}
        onNewRecord={() => {}}
        onRetry={() => {}}
        onStatusChange={() => {}}
      />,
    )
    const labels = ['待人工复核', '已投递', '笔试 / 测评', '面试', '已结束']
    labels.forEach((label) => {
      expect(screen.getByRole('region', { name: label })).toBeInTheDocument()
    })
    const pendingColumn = screen.getByRole('region', { name: '待人工复核' })
    expect(pendingColumn).toHaveTextContent('待人工复核')
    expect(pendingColumn).toHaveTextContent('1')
    expect(screen.getAllByText('暂无记录').length).toBe(4)
  })

  it('按 current_status 把卡片分组到正确列，面试列显示轮次', () => {
    const records = [
      makeRecord({ id: 1, company_name: '示例科技', current_status: 'pending_review' }),
      makeRecord({ id: 2, company_name: '示例网络', current_status: 'applied' }),
      makeRecord({ id: 3, company_name: '示例云', current_status: 'interview_1' }),
      makeRecord({ id: 4, company_name: '示例数据', current_status: 'offer' }),
      makeRecord({ id: 5, company_name: '示例安全', current_status: 'assessment' }),
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
    expect(screen.getByRole('region', { name: '待人工复核' })).toHaveTextContent('示例科技')
    expect(screen.getByRole('region', { name: '已投递' })).toHaveTextContent('示例网络')
    const interviewColumn = screen.getByRole('region', { name: '面试' })
    expect(interviewColumn).toHaveTextContent('示例云')
    expect(interviewColumn).toHaveTextContent('1面')
    expect(screen.getByRole('region', { name: '已结束' })).toHaveTextContent('Offer')
    expect(screen.getByRole('region', { name: '笔试 / 测评' })).toHaveTextContent('示例安全')
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
    render(
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
        onStatusChange={onStatusChange}
      />,
    )
    const card = screen.getByTestId('board-card-7')
    await dragToGroup(card, 'applied')
    await waitFor(() => {
      expect(onStatusChange).toHaveBeenCalledTimes(1)
      expect(onStatusChange).toHaveBeenCalledWith(record, 'applied')
    })
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

  it('键盘传感器启用：卡片可聚焦，Space 开始、Esc 取消不报错', async () => {
    const record = makeRecord({ id: 9, company_name: '示例科技' })
    const onStatusChange = vi.fn()
    const user = userEvent.setup()
    render(
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
        onStatusChange={onStatusChange}
      />,
    )
    const card = screen.getByTestId('board-card-9')
    expect(card).toHaveAttribute('role', 'button')
    expect(card).toHaveAttribute('aria-roledescription', 'draggable')
    card.focus()
    await user.keyboard(' ')
    await user.keyboard('{Escape}')
    expect(onStatusChange).not.toHaveBeenCalled()
  })
})
