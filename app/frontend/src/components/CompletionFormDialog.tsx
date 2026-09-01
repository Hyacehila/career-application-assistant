import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { patchEvent, type ApplicationEvent, type ApplicationRecord } from '../api/client'
import { todayDate } from '../lib/dates'
import { statusLabelOf } from '../lib/statuses'
import OverlayShell from './OverlayShell'

export interface CompletionFormDialogProps {
  record: ApplicationRecord
  event: ApplicationEvent
  onDone: (message: string) => void
  onError?: (message: string) => void
  onClose: () => void
}

export default function CompletionFormDialog({
  record,
  event,
  onDone,
  onError,
  onClose,
}: CompletionFormDialogProps) {
  const today = todayDate()
  const existingDate = event.completed_date ?? ''
  const [completedDate, setCompletedDate] = useState(existingDate || today)
  const [pendingAction, setPendingAction] = useState<'save' | 'clear' | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const stageLabel = statusLabelOf(event.stage)
  const isAssessment = event.stage === 'assessment'

  const title = useMemo(() => {
    if (existingDate) return isAssessment ? '修改笔试 / 测评完成状态' : `修改${stageLabel}完成状态`
    return isAssessment ? '标记笔试 / 测评已完成' : `标记${stageLabel}已结束`
  }, [existingDate, isAssessment, stageLabel])

  const submit = async (nextDate: string | null, action: 'save' | 'clear') => {
    setPendingAction(action)
    setSubmitError(null)
    try {
      await patchEvent(record.id, event.id, { completed_date: nextDate })
      onDone(nextDate === null ? '已撤销完成标记' : '完成状态已保存')
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : '完成状态保存失败，请稍后重试'
      setSubmitError(message)
      setPendingAction(null)
      onError?.(message)
    }
  }

  const handleSubmit = (formEvent: FormEvent) => {
    formEvent.preventDefault()
    if (!completedDate || completedDate > today || pendingAction) return
    void submit(completedDate, 'save')
  }

  const busy = pendingAction !== null

  return (
    <OverlayShell title={title} onClose={onClose} compact>
      <form className="formStack" onSubmit={handleSubmit}>
        <p className="formNotice">
          {isAssessment
            ? '完成后，卡片将显示「笔试 / 测评 · 已完成」。完成状态不会自动推进到下一阶段。'
            : `完成后，卡片将显示「${stageLabel} · 已结束」。完成状态不会自动推进到下一阶段。`}
        </p>
        <div className="formField">
          <label htmlFor="completion-form-date" className="formLabel formLabelRequired">
            完成日期（必填）
          </label>
          <input
            id="completion-form-date"
            className="formInput"
            type="date"
            required
            max={today}
            value={completedDate}
            onChange={(inputEvent) => setCompletedDate(inputEvent.target.value)}
            data-testid="completion-form-date"
          />
          <span className="formHint">不可晚于今天（Asia/Shanghai）</span>
        </div>
        {submitError && (
          <p className="formHint" role="alert" data-testid="completion-form-error" style={{ color: 'var(--color-rejected)' }}>
            {submitError}
          </p>
        )}
        <div className="dialogActions dialogActionsSplit">
          <div>
            {existingDate && (
              <button
                type="button"
                className="dangerButton"
                disabled={busy}
                onClick={() => void submit(null, 'clear')}
                data-testid="completion-form-clear"
              >
                {pendingAction === 'clear' ? '撤销中…' : '撤销完成标记'}
              </button>
            )}
          </div>
          <div className="dialogActionsGroup">
            <button type="button" className="secondaryButton" onClick={onClose} disabled={busy}>
              取消
            </button>
            <button
              type="submit"
              className="primaryButton"
              disabled={!completedDate || completedDate > today || busy}
              data-testid="completion-form-submit"
            >
              {pendingAction === 'save' ? '保存中…' : existingDate ? '保存修改' : '确认完成'}
            </button>
          </div>
        </div>
      </form>
    </OverlayShell>
  )
}
