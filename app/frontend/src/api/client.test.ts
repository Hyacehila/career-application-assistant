import { afterEach, describe, expect, it, vi } from 'vitest'
import { APIError, listAllApplications, listApplications } from './client'
import { jsonBody } from '../test/http'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('构造 /api/applications 查询参数（camelCase 映射为 snake_case）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonBody({ items: [], total: 0, page: 2, page_size: 10 }))
    vi.stubGlobal('fetch', fetchMock)
    const payload = await listApplications({ stageGroup: 'interview', sort: '-updated_at', page: 2, pageSize: 10 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/applications?stage_group=interview&sort=-updated_at&page=2&page_size=10')
    expect(payload.items).toEqual([])
  })

  it('非 2xx 响应抛出包含 code/message 的错误', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonBody({ code: 'name_conflict', message: '记录已存在' }, 409))
    vi.stubGlobal('fetch', fetchMock)
    const promise = listApplications({ q: '示例' })
    await expect(promise).rejects.toBeInstanceOf(APIError)
    await expect(promise).rejects.toMatchObject({ name: 'APIError', code: 'name_conflict', message: '记录已存在', status: 409 })
  })

  it('网络失败包装为 APIError', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('fetch failed'))
    vi.stubGlobal('fetch', fetchMock)
    await expect(listApplications()).rejects.toMatchObject({ name: 'APIError', code: 'network_error' })
  })

  it('看板列表并行读取全部分页，超过 100 条时不静默丢失', async () => {
    const records = Array.from({ length: 205 }, (_, index) => ({ id: index + 1 }))
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://local.test')
      const page = Number(url.searchParams.get('page'))
      const pageSize = Number(url.searchParams.get('page_size'))
      const start = (page - 1) * pageSize
      return Promise.resolve(jsonBody({
        items: records.slice(start, start + pageSize),
        total: records.length,
        page,
        page_size: pageSize,
        counts: { pending_review: 203, applied: 0, assessment: 0, interview: 1, ended: 1 },
        options: { types: [], cities: [], sources: [] },
      }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const payload = await listAllApplications({ sort: '-company_name' })

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      '/api/applications?sort=-company_name&page=1&page_size=100',
      '/api/applications?sort=-company_name&page=2&page_size=100',
      '/api/applications?sort=-company_name&page=3&page_size=100',
    ])
    expect(payload.items).toHaveLength(205)
    expect(payload.items.at(-1)).toMatchObject({ id: 205 })
    expect(payload.counts).toMatchObject({ pending_review: 203, interview: 1, ended: 1 })
  })
})
