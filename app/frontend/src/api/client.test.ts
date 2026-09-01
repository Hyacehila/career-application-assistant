import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  APIError,
  dismissMailCandidate,
  health,
  listAllApplications,
  listApplications,
  pauseMailAccount,
  resumeMailAccount,
  resetDemo,
  syncMailAccount,
} from './client'
import { jsonBody } from '../test/http'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('读取类型化 health 并以空 JSON 请求重置 Demo', async () => {
    const healthPayload = {
      status: 'ok',
      database: 'ready',
      schema_version: 4,
      service: 'career-application-assistant',
      mode: 'demo',
      synthetic_data: true,
      mail_ingestion: false,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      if (String(input) === '/api/health') return Promise.resolve(jsonBody(healthPayload))
      return Promise.resolve(jsonBody({ ok: true, records_seeded: 6 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(health()).resolves.toEqual(healthPayload)
    await expect(resetDemo()).resolves.toEqual({ ok: true, records_seeded: 6 })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/demo/reset')
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST', body: '{}' })
  })

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

  it('无参数邮箱写操作仍发送 JSON 空对象', async () => {
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/dismiss')) return Promise.resolve(new Response(null, { status: 204 }))
      if (url.endsWith('/sync')) return Promise.resolve(jsonBody({ operation_id: 'op-1', status: 'pending' }, 202))
      return Promise.resolve(jsonBody({
        provider: 'qq',
        status: url.endsWith('/pause') ? 'paused' : 'connected',
        masked_address: null,
        history_window: 'new_only',
        last_attempt_at: null,
        last_success_at: null,
        next_retry_at: null,
        error_code: null,
        pending_count: 0,
      }))
    })
    vi.stubGlobal('fetch', fetchMock)

    await syncMailAccount('qq')
    await pauseMailAccount('qq')
    await resumeMailAccount('qq')
    await dismissMailCandidate(7)

    expect(fetchMock).toHaveBeenCalledTimes(4)
    for (const [, init] of fetchMock.mock.calls) {
      expect(init).toMatchObject({ method: 'POST', body: '{}' })
      expect(new Headers((init as RequestInit).headers).get('Content-Type')).toBe('application/json')
    }
  })
})
