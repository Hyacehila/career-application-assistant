import { useState } from 'react'
import Check from 'lucide-react/dist/esm/icons/check'
import OverlayShell from './OverlayShell'

export interface ConfirmDialogProps {
  title: string
  message: string
  confirmLabel?: string
  danger?: boolean
  onConfirm: () => Promise<void> | void
  onDone?: () => void
  onError?: (message: string) => void
  onClose: () => void
}

export default function ConfirmDialog({
  title,
  message,
  confirmLabel = '确认',
  danger = false,
  onConfirm,
  onDone,
  onError,
  onClose,
}: ConfirmDialogProps) {
  const [pending, setPending] = useState(false)

  const handleConfirm = async () => {
    if (pending) return
    setPending(true)
    try {
      await onConfirm()
      onDone?.()
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : '操作失败，请稍后重试'
      onError?.(message)
      setPending(false)
    }
  }

  return (
    <OverlayShell title={title} onClose={onClose}>
      <p className="formNotice">{message}</p>
      <div className="dialogActions">
        <button type="button" className="secondaryButton" onClick={onClose} disabled={pending}>
          取消
        </button>
        <button
          type="button"
          className={danger ? 'dangerButton' : 'primaryButton'}
          data-testid="confirm-dialog-confirm"
          onClick={handleConfirm}
          disabled={pending}
        >
          {!danger && <Check size={16} aria-hidden="true" />}
          {pending ? '处理中…' : confirmLabel}
        </button>
      </div>
    </OverlayShell>
  )
}
