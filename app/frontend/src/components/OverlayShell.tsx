import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '../lib/classNames'
import { useReducedMotion } from '../lib/useReducedMotion'

interface OverlayShellProps {
  title: string
  onClose: () => void
  children: ReactNode
  labelledBy?: string
}

const OPEN_ANIMATION_MS = 210

export default function OverlayShell({ title, onClose, children, labelledBy }: OverlayShellProps) {
  const reduced = useReducedMotion()
  const [closing, setClosing] = useState(false)
  const cardRef = useRef<HTMLDivElement | null>(null)
  const activeElement = useRef<HTMLElement | null>(null)

  const requestClose = () => {
    if (closing) return
    setClosing(true)
    if (reduced) onClose()
  }

  useEffect(() => {
    activeElement.current = document.activeElement as HTMLElement | null
    const card = cardRef.current
    const firstInput = card?.querySelector<HTMLElement>('input, select, textarea')
    const firstFocusable = firstInput ?? card?.querySelector<HTMLElement>('button, a[href]')
    firstFocusable?.focus()
    return () => {
      activeElement.current?.focus?.()
    }
  }, [])

  useEffect(() => {
    if (!closing) return undefined
    const timer = window.setTimeout(onClose, reduced ? 0 : OPEN_ANIMATION_MS)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closing, reduced])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key === 'Tab' && cardRef.current) {
        const focusables = Array.from(
          cardRef.current.querySelectorAll<HTMLElement>('button, input, select, textarea, a[href]'),
        ).filter((element) => !element.hasAttribute('disabled'))
        if (focusables.length === 0) return
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', handleKeyDown, true)
    return () => document.removeEventListener('keydown', handleKeyDown, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const titleId = labelledBy ?? `overlay-title-${title}`

  return (
    <div
      className={cn('overlayLayer', closing && 'overlayLayerEnd')}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) requestClose()
      }}
    >
      <div
        ref={cardRef}
        className={cn('overlayCard', closing && 'overlayCardEnd')}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        aria-labelledby={titleId}
      >
        <div className="overlayCardHead">
          <h2 id={titleId} className="overlayCardTitle">
            {title}
          </h2>
          <button type="button" className="overlayCardClose" aria-label="关闭" onClick={requestClose}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
