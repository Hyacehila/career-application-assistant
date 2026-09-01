import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ApplicationRecord } from '../api/client'
import { makeRecord } from '../test/fixtures'
import TableView from './TableView'

function baseProps(overrides: Partial<Parameters<typeof TableView>[0]> = {}) {
  return {
    items: [
      makeRecord({ id: 1, company_name: '示例科技', job_title: '前端工程师' }),
      makeRecord({ id: 2, company_name: '示例网络', job_title: '后端工程师', current_status: 'applied', submitted_at: '2026-08-10T10:00:00+08:00', updated_at: '2026-08-11T10:00:00+08:00' }),
    ],
    total: 2,
    page: 1,
    pageSize: 20,
    loading: false,
    error: null,
    sort: 'updated_at',
    selectedId: null,
    onOpen: () => {},
    onSortChange: () => {},
    onPageChange: () => {},
    onRetry: () => {},
    ...overrides,
  }
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TableView', () => {
  it('按固定顺序渲染九列', () => {
    render(<TableView {...baseProps()} />)
    const headers = screen.getAllByRole('columnheader').map((header) => header.textContent)
    expect(headers).toEqual([
      '公司',
      '岗位',
      '类型',
      '地点',
      '当前阶段',
      '阶段日期',
      '投递日期',
      '来源',
      '更新时间',
    ])
  })

  it('点击可排序列头调用 onSortChange 切换方向', async () => {
    const onSortChange = vi.fn()
    const user = userEvent.setup()
    render(<TableView {...baseProps({ onSortChange, sort: 'updated_at' })} />)
    await user.click(screen.getByTestId('table-sort-company'))
    expect(onSortChange).toHaveBeenLastCalledWith('company_name')
    cleanup()
    render(<TableView {...baseProps({ onSortChange, sort: 'company_name' })} />)
    await user.click(screen.getByTestId('table-sort-company'))
    expect(onSortChange).toHaveBeenLastCalledWith('-company_name')
    cleanup()
    render(<TableView {...baseProps({ onSortChange, sort: '-updated_at' })} />)
    await user.click(screen.getByTestId('table-sort-updated'))
    expect(onSortChange).toHaveBeenLastCalledWith('updated_at')
  })

  it('渲染分页条并调用 onPageChange', async () => {
    const onPageChange = vi.fn()
    const items = Array.from({ length: 20 }, (_, index) =>
      makeRecord({ id: index + 1, company_name: `示例公司${index + 1}` }),
    )
    render(
      <TableView
        {...baseProps({
          items,
          total: 45,
          page: 2,
          pageSize: 20,
          onPageChange,
        })}
      />,
    )
    expect(screen.getByTestId('table-pagination-info')).toHaveTextContent('第 2 / 3 页 · 共 45 条')
    const user = userEvent.setup()
    const nextButton = screen.getByRole('button', { name: '下一页' })
    expect(nextButton).toBeEnabled()
    await user.click(nextButton)
    expect(onPageChange).toHaveBeenCalledWith(3)
    const prevButton = screen.getByRole('button', { name: '上一页' })
    expect(prevButton).toBeEnabled()
  })

  it('点击行打开抽屉（onOpen 回调）', async () => {
    const onOpen = vi.fn()
    render(<TableView {...baseProps({ onOpen })} />)
    const user = userEvent.setup()
    await user.click(screen.getByTestId('table-row-2'))
    expect(onOpen).toHaveBeenCalledWith(2)
  })

  it('表格行可聚焦，Enter 打开抽屉', async () => {
    const onOpen = vi.fn()
    render(<TableView {...baseProps({ onOpen })} />)
    const user = userEvent.setup()
    const row = screen.getByTestId('table-row-1')
    row.focus()
    await user.keyboard('{Enter}')
    expect(onOpen).toHaveBeenCalledWith(1)
  })

  it('当前阶段显示共享状态文案与语义日期，投递日期缺省显示 —', () => {
    render(<TableView {...baseProps()} />)
    expect(screen.getByTestId('table-row-1')).toHaveTextContent('创建于 2026-08-20')
    expect(screen.getByTestId('table-row-2')).toHaveTextContent('投递于 2026-08-10')
    expect(screen.getByTestId('table-row-2')).toHaveTextContent('2026-08-10')
    expect(screen.getByTestId('table-row-1')).toHaveTextContent('—')
  })
})
