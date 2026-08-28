import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Filters from './Filters'

describe('Filters', () => {
  it('状态分组使用内部值并能正确回显与更新 ended', async () => {
    const onStageGroupChange = vi.fn()
    render(
      <Filters
        type=""
        city=""
        source=""
        sort="updated_at"
        stageGroup="ended"
        options={{ types: [], cities: [], sources: [] }}
        onTypeChange={() => {}}
        onCityChange={() => {}}
        onSourceChange={() => {}}
        onSortChange={() => {}}
        onStageGroupChange={onStageGroupChange}
      />,
    )
    const select = screen.getByLabelText('状态分组')
    expect(select).toHaveValue('ended')
    await userEvent.setup().selectOptions(select, 'interview')
    expect(onStageGroupChange).toHaveBeenCalledWith('interview')
  })
})
