import { useCallback, useEffect, useState } from 'react'
import { getApplication, type ApplicationDetail } from '../api/client'

export interface DetailState {
  loading: boolean
  error: { code: string; message: string } | null
  data: ApplicationDetail | null
}

export function useApplicationDetail(id: number | null): DetailState & { refetch: () => void } {
  const [state, setState] = useState<DetailState>({ loading: id !== null, error: null, data: null })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (id === null) {
      setState({ loading: false, error: null, data: null })
      return undefined
    }
    const controller = new AbortController()
    setState((previous) => ({ ...previous, loading: true, error: null }))
    getApplication(id, controller.signal)
      .then((detail) => {
        setState({ loading: false, error: null, data: detail })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        const code = error && typeof error === 'object' && 'code' in error ? String((error as { code: unknown }).code) : 'unknown'
        const message =
          error && typeof error === 'object' && 'message' in error && String((error as { message: unknown }).message) !== ''
            ? String((error as { message: unknown }).message)
            : '加载详情失败，请稍后重试'
        setState((previous) => ({ ...previous, loading: false, error: { code, message } }))
      })
    return () => {
      controller.abort()
    }
  }, [id, tick])

  const refetch = useCallback(() => {
    setTick((value) => value + 1)
  }, [])

  return { ...state, refetch }
}
