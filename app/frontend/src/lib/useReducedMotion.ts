import { useEffect, useRef, useState } from 'react'

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false,
  )

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handleChange = (event: MediaQueryListEvent) => setReduced(event.matches)
    query.addEventListener('change', handleChange)
    return () => {
      query.removeEventListener('change', handleChange)
    }
  }, [])

  return reduced
}
