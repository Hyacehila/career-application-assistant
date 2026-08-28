import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '../lib/classNames'
import { useReducedMotion } from '../lib/useReducedMotion'

export type ToastTone = 'success' | 'error'

export interface ToastItem {
  id: number
  tone: ToastTone
  message: string
  ending: boolean
}

let nextToastId = 1

export interface UseToastsResult {
  toasts: ToastItem[]
  showToast: (message: string, tone?: ToastTone) => void
}

const TOAST_DURATION_MS = 4000

export function useToasts(): UseToastsResult {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const reduced = useReducedMotion()
  const endingTimers = useRef<Map<number, number>>(new Map())

  const showToast = useCallback(
    (message: string, tone: ToastTone = 'success') => {
      const id = nextToastId
      nextToastId += 1
      setToasts((previous) => [...previous, { id, tone, message, ending: false }])
      const enterTimer = window.setTimeout(() => {
        setToasts((previous) => previous.map((item) => (item.id === id ? { ...item, ending: true } : item)))
        const removeTimer = window.setTimeout(() => {
          setToasts((previous) => previous.filter((item) => item.id !== id))
          endingTimers.current.delete(id)
        }, reduced ? 0 : 200)
        endingTimers.current.set(id, removeTimer)
      }, reduced ? 0 : TOAST_DURATION_MS)
      endingTimers.current.set(id, enterTimer)
    },
    [reduced],
  )

  useEffect(() => {
    const timers = endingTimers.current
    return () => {
      for (const timer of timers.values()) window.clearTimeout(timer)
      timers.clear()
    }
  }, [])

  return { toasts, showToast }
}

export function ToastViewport({ toasts }: { toasts: ToastItem[] }) {
  return (
    <div className="toastViewport" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cn('toastCard', toast.tone === 'success' && 'toastSuccess', toast.tone === 'error' && 'toastError')}
        >
          {toast.message}
        </div>
      ))}
    </div>
  )
}
