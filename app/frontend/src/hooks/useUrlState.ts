import { useCallback, useEffect, useRef, useState } from 'react'

export type ViewName = 'board' | 'table'

export interface UrlStateValue {
  view: ViewName
  q: string
  stageGroup: string
  status: string
  type: string
  city: string
  source: string
  sort: string
  page: number
  pageSize: number
}

const DEFAULT_VIEW: ViewName = 'board'
const DEFAULT_SORT = 'updated_at'
const DEFAULT_PAGE = 1
const DEFAULT_PAGE_SIZE = 20

export const DEFAULT_URL_STATE: UrlStateValue = {
  view: DEFAULT_VIEW,
  q: '',
  stageGroup: '',
  status: '',
  type: '',
  city: '',
  source: '',
  sort: DEFAULT_SORT,
  page: DEFAULT_PAGE,
  pageSize: DEFAULT_PAGE_SIZE,
}

function parseUrlState(search: string): UrlStateValue {
  const params = new URLSearchParams(search)
  const viewParam = params.get('view')
  const pageParam = params.get('page')
  const pageSizeParam = params.get('page_size')
  const page = pageParam ? Math.max(1, Math.floor(Number(pageParam)) || 1) : DEFAULT_PAGE
  const parsedPageSize = pageSizeParam ? Math.floor(Number(pageSizeParam)) : DEFAULT_PAGE_SIZE
  const pageSize = Number.isFinite(parsedPageSize) && parsedPageSize >= 1
    ? Math.min(100, parsedPageSize)
    : DEFAULT_PAGE_SIZE
  const sort = params.get('sort') ?? DEFAULT_SORT
  return {
    view: viewParam === 'table' ? 'table' : DEFAULT_VIEW,
    q: params.get('q') ?? '',
    stageGroup: params.get('stage_group') ?? '',
    status: params.get('status') ?? '',
    type: params.get('type') ?? '',
    city: params.get('city') ?? '',
    source: params.get('source') ?? '',
    sort,
    page,
    pageSize,
  }
}

function toSearchParams(value: UrlStateValue): URLSearchParams {
  const params = new URLSearchParams()
  if (value.view !== DEFAULT_VIEW) params.set('view', value.view)
  if (value.q !== '') params.set('q', value.q)
  if (value.stageGroup !== '') params.set('stage_group', value.stageGroup)
  if (value.status !== '') params.set('status', value.status)
  if (value.type !== '') params.set('type', value.type)
  if (value.city !== '') params.set('city', value.city)
  if (value.source !== '') params.set('source', value.source)
  if (value.sort !== DEFAULT_SORT) params.set('sort', value.sort)
  if (value.page !== DEFAULT_PAGE) params.set('page', String(value.page))
  if (value.pageSize !== DEFAULT_PAGE_SIZE) params.set('page_size', String(value.pageSize))
  return params
}

function normalizePage(value: number): number {
  return Number.isFinite(value) && value >= 1 ? Math.floor(value) : DEFAULT_PAGE
}

function serialize(next: UrlStateValue): string {
  const query = toSearchParams(next).toString()
  return query ? `?${query}` : window.location.pathname
}

function isFilterKey(key: keyof UrlStateValue): boolean {
  return (
    key === 'q' ||
    key === 'stageGroup' ||
    key === 'status' ||
    key === 'type' ||
    key === 'city' ||
    key === 'source' ||
    key === 'sort'
  )
}

export function useUrlState(): [
  UrlStateValue,
  (patch: Partial<UrlStateValue>, options?: { push?: boolean }) => void,
] {
  const [state, setState] = useState<UrlStateValue>(() => parseUrlState(window.location.search))
  const stateRef = useRef(state)

  useEffect(() => {
    stateRef.current = state
  }, [state])

  const update = useCallback(
    (patch: Partial<UrlStateValue>, options: { push?: boolean } = {}) => {
      const current = stateRef.current
      const hasPage = patch.page !== undefined
      const hasFilter = Object.keys(patch).some((key) => isFilterKey(key as keyof UrlStateValue))
      const next: UrlStateValue = {
        ...current,
        ...patch,
        page: hasPage ? normalizePage(patch.page ?? current.page) : hasFilter ? DEFAULT_PAGE : current.page,
      }
      const nextSearch = serialize(next)
      const shouldPush = options.push === true && patch.view !== undefined && patch.view !== current.view
      if (shouldPush) {
        window.history.pushState(null, '', nextSearch)
      } else {
        window.history.replaceState(null, '', nextSearch)
      }
      stateRef.current = next
      setState(next)
    },
    [],
  )

  return [state, update]
}