import { useEffect, useState } from 'react'
import { health, type HealthResponse } from '../api/client'

export interface ServiceHealthResult {
  data: HealthResponse | null
  loading: boolean
}

export function useServiceHealth(): ServiceHealthResult {
  const [data, setData] = useState<HealthResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    health(controller.signal)
      .then((payload) => {
        setData(payload)
        setLoading(false)
      })
      .catch(() => {
        if (controller.signal.aborted) return
        setLoading(false)
      })
    return () => controller.abort()
  }, [])

  return { data, loading }
}
