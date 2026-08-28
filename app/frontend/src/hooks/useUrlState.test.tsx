import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { DEFAULT_URL_STATE, useUrlState, type UrlStateValue } from './useUrlState'

function UrlProbe() {
  const [state, update] = useUrlState()
  return (
    <div>
      <span data-testid="state">{JSON.stringify(state)}</span>
      <button data-testid="view" onClick={() => update({ view: 'table' })}>
        切换视图
      </button>
      <button data-testid="q" onClick={() => update({ q: '示例科技' })}>
        设置搜索
      </button>
      <button data-testid="clear" onClick={() => update({ q: '' })}>
        清空搜索
      </button>
      <button data-testid="page" onClick={() => update({ page: 3 })}>
        设置页码
      </button>
      <button data-testid="filter" onClick={() => update({ type: '实习' })}>
        设置筛选
      </button>
    </div>
  )
}

function currentState(): UrlStateValue {
  return JSON.parse(screen.getByTestId('state').textContent ?? '{}')
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

afterEach(() => {
  cleanup()
})

describe('useUrlState', () => {
  it('默认值：view=board、sort=updated_at、page=1、pageSize=20', () => {
    render(<UrlProbe />)
    expect(currentState()).toEqual(DEFAULT_URL_STATE)
    expect(window.location.search).toBe('')
  })

  it('写入 URL 参数并可读回，空值省略', async () => {
    const user = userEvent.setup()
    render(<UrlProbe />)
    await user.click(screen.getByTestId('q'))
    expect(window.location.search).toBe(`?q=${encodeURIComponent('示例科技')}`)
    expect(currentState().q).toBe('示例科技')
    await user.click(screen.getByTestId('clear'))
    expect(window.location.search).toBe('')
    expect(currentState().q).toBe('')
  })

  it('切换视图写入 view=table', async () => {
    const user = userEvent.setup()
    render(<UrlProbe />)
    await user.click(screen.getByTestId('view'))
    expect(window.location.search).toBe('?view=table')
    expect(currentState().view).toBe('table')
  })

  it('筛选变化重置 page；page 显式写入非默认值', async () => {
    const user = userEvent.setup()
    render(<UrlProbe />)
    await user.click(screen.getByTestId('page'))
    expect(window.location.search).toBe('?page=3')
    expect(currentState().page).toBe(3)
    await user.click(screen.getByTestId('filter'))
    expect(window.location.search).toBe(`?type=${encodeURIComponent('实习')}`)
    expect(currentState().page).toBe(1)
  })

  it('从 URL 初始化（刷新恢复状态）', () => {
    window.history.replaceState(null, '', '/?view=table&stage_group=assessment&sort=-updated_at&page=2&page_size=50')
    render(<UrlProbe />)
    expect(currentState()).toMatchObject({
      view: 'table',
      stageGroup: 'assessment',
      sort: '-updated_at',
      page: 2,
      pageSize: 50,
    })
  })
})