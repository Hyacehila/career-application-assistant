import { useCallback, useEffect, useState } from 'react'
import {
  APIError,
  listAllApplications,
  listApplications,
  type BoardGroupCounts,
  type ListApplicationsResponse,
  type ListOptions,
} from '../api/client'
import type { UrlStateValue } from './useUrlState'

export interface BoardQueryError {
  code: string
  message: string
}

export interface BoardQueryResult {
  data: ListApplicationsResponse
  counts: BoardGroupCounts
  options: ListOptions
  loading: boolean
  error: BoardQueryError | null
  refetch: () => void
}

const DEFAULT_RESPONSE: ListApplicationsResponse = {
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  counts: {
    pending_review: 0,
    applied: 0,
    assessment: 0,
    interview: 0,
    ended: 0,
  },
  options: {
    types: [],
    cities: [],
    sources: [],
  },
}

function toQueryError(error: unknown): BoardQueryError {
  if (error instanceof APIError) {
    return { code: error.code, message: error.message }
  }
  if (error instanceof Error && error.message) {
    return { code: 'request_failed', message: error.message }
  }
  return { code: 'request_failed', message: '加载投递记录失败，请检查后端服务是否已启动。' }
}

export function useBoardQuery(query: UrlStateValue, enabled = true): BoardQueryResult {
  const [result, setResult] = useState<{
    data: ListApplicationsResponse
    error: BoardQueryError | null
  }>({ data: DEFAULT_RESPONSE, error: null })
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)

  const refetch = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    const filters = {
      q: query.q || undefined,
      stageGroup: query.stageGroup || undefined,
      status: query.status || undefined,
      type: query.type || undefined,
      city: query.city || undefined,
      source: query.source || undefined,
      sort: query.sort,
      signal: controller.signal,
    }
    const request = query.view === 'board'
      ? listAllApplications(filters)
      : listApplications({ ...filters, page: query.page, pageSize: query.pageSize })
    request
      .then((payload) => {
        setResult({ data: payload, error: null })
        setLoading(false)
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        setResult((previous) => ({ ...previous, error: toQueryError(error) }))
        setLoading(false)
      })
    return () => {
      controller.abort()
    }
  }, [enabled, query, tick])

  return {
    data: result.data,
    counts: result.data.counts,
    options: result.data.options,
    loading,
    error: result.error,
    refetch,
  }
}
