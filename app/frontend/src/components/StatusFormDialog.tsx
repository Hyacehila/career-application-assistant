import { useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { postEvent, type ApplicationRecord, type EventPayload } from '../api/client'
import { cn } from '../lib/classNames'
import { todayDate } from '../lib/dates'
import { BOARD_GROUP_LABELS, STATUS_LABELS, STATUSES, type Status } from '../lib/statuses'
import OverlayShell from './OverlayShell'

export type StatusFormTarget = 'applied' | 'assessment' | 'interview' | 'ended' | 'free'

export interface StatusFormDialogProps {
  target: StatusFormTarget
  record: ApplicationRecord
  onDone?: () => void
  onError?: (message: string) => void
  onClose: () => void
}

const INTERVIEW_ROUNDS: Array<{ value: Status; label: string }> = [
  { value: 'interview_1', label: '1面' },
  { value: 'interview_2', label: '2面' },
  { value: 'interview_3', label: '3面' },
  { value: 'interview_hr', label: 'HR面' },
]

const ENDED_OUTCOMES: Array<{ value: Status; label: string }> = [
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: '拒绝' },
  { value: 'withdrawn', label: '撤回' },
]

const MODE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'online', label: '线上' },
  { value: 'offline', label: '线下' },
  { value: 'phone', label: '电话' },
]

const DEFAULT_TARGET_STAGE: Record<Exclude<StatusFormTarget, 'free'>, Status> = {
  applied: 'applied',
  assessment: 'assessment',
  interview: 'interview_1',
  ended: 'offer',
}

function RadioGroup({
  name,
  legend,
  options,
  value,
  onChange,
}: {
  name: string
  legend: string
  options: Array<{ value: string; label: string }>
  value: string
  onChange: (value: string) => void
}) {
  return (
    <fieldset className="formField" style={{ border: 0, margin: 0, padding: 0 }}>
      <legend className={cn('formLabel', 'formLabelRequired')}>{legend}（必填）</legend>
      <div className="formRadioGroup" role="radiogroup" aria-label={legend}>
        {options.map((option) => (
          <label key={option.value} className={cn('formRadio', value === option.value && 'formRadioActive')}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function DateField({
  id,
  label,
  value,
  onChange,
  required,
  testId,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  required?: boolean
  testId?: string
}) {
  return (
    <div className="formField">
      <label htmlFor={id} className={cn('formLabel', required && 'formLabelRequired')}>
        {label}
        {required ? '（必填）' : '（可选）'}
      </label>
      <input
        id={id}
        className="formInput"
        type="date"
        required={required}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-testid={testId}
      />
    </div>
  )
}

function TimeField({
  id,
  label,
  value,
  onChange,
  disabled,
  testId,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  testId?: string
}) {
  return (
    <div className="formField">
      <label htmlFor={id} className={cn('formLabel', 'formLabelOptional')}>
        {label}（可选）
      </label>
      <input
        id={id}
        className="formInput"
        type="time"
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-testid={testId}
      />
    </div>
  )
}

export default function StatusFormDialog({ target, record, onDone, onError, onClose }: StatusFormDialogProps) {
  const isFree = target === 'free'
  const [stage, setStage] = useState<Status>(
    isFree ? (record.current_status as Status) : DEFAULT_TARGET_STAGE[target],
  )
  const [eventDate, setEventDate] = useState(todayDate())
  const [scheduledDate, setScheduledDate] = useState('')
  const [scheduledTime, setScheduledTime] = useState('')
  const [deadlineDate, setDeadlineDate] = useState('')
  const [deadlineTime, setDeadlineTime] = useState('')
  const [mode, setMode] = useState('')
  const [location, setLocation] = useState('')
  const [appliedConfirmed, setAppliedConfirmed] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const title = useMemo(() => {
    if (isFree) return `更新状态 · ${record.company_name} ${record.job_title}`
    return `更新到“${BOARD_GROUP_LABELS[target]}” · ${record.company_name} ${record.job_title}`
  }, [isFree, target, record])

  const interviewSelected = target === 'interview' || (isFree && stage.startsWith('interview_'))
  const assessmentSelected = target === 'assessment' || (isFree && stage === 'assessment')
  const appliedSelected = stage === 'applied'

  const missingAssessmentDate = assessmentSelected && scheduledDate === '' && deadlineDate === ''
  const missingInterviewDate = interviewSelected && scheduledDate === ''
  const missingDate = isFree && eventDate === ''
  const canSubmit =
    eventDate !== '' &&
    !missingAssessmentDate &&
    !missingInterviewDate &&
    !missingDate &&
    (!appliedSelected || appliedConfirmed) &&
    !pending

  const handleEventDate = (value: string) => setEventDate(value)
  const handleScheduledDate = (value: string) => {
    setScheduledDate(value)
    if (!value) setScheduledTime('')
  }
  const handleDeadlineDate = (value: string) => {
    setDeadlineDate(value)
    if (!value) setDeadlineTime('')
  }

  const buildPayload = (): EventPayload => {
    const payload: EventPayload = {
      stage,
      event_date: eventDate,
      source: appliedSelected ? 'user_confirmation' : 'manual_ui',
    }
    if (interviewSelected) {
      payload.scheduled_date = scheduledDate
      if (scheduledTime) payload.scheduled_time = scheduledTime
      if (mode) payload.mode = mode
      if (location.trim()) payload.location = location.trim()
    }
    if (assessmentSelected) {
      if (scheduledDate) payload.scheduled_date = scheduledDate
      if (scheduledTime) payload.scheduled_time = scheduledTime
      if (deadlineDate) payload.deadline_date = deadlineDate
      if (deadlineTime) payload.deadline_time = deadlineTime
    }
    return payload
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return
    setPending(true)
    try {
      await postEvent(record.id, buildPayload())
      onDone?.()
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : '状态更新失败，请稍后重试'
      setSubmitError(message)
      onError?.(message)
      setPending(false)
    }
  }

  return (
    <OverlayShell title={title} onClose={onClose}>
      <form className="formStack" onSubmit={handleSubmit}>
        {appliedSelected && (
          <p className="formNotice">请确认你已经手动完成最终提交，提交后记录将进入“已投递”。</p>
        )}
        {appliedSelected && (
          <label className="formConfirmation" htmlFor="status-form-applied-confirmed">
            <input
              id="status-form-applied-confirmed"
              type="checkbox"
              checked={appliedConfirmed}
              onChange={(event) => setAppliedConfirmed(event.target.checked)}
            />
            <span>我确认已亲自完成最终提交</span>
          </label>
        )}
        {isFree && (
          <RadioGroup
            name="status-form-stage"
            legend="目标状态"
            options={STATUSES.map((status) => ({ value: status, label: STATUS_LABELS[status] }))}
            value={stage}
            onChange={(value) => {
              setStage(value as Status)
              setAppliedConfirmed(false)
            }}
          />
        )}
        {target === 'interview' && (
          <RadioGroup
            name="status-form-round"
            legend="面试轮次"
            options={INTERVIEW_ROUNDS.map((option) => ({ value: option.value, label: option.label }))}
            value={stage}
            onChange={(value) => setStage(value as Status)}
          />
        )}
        {target === 'ended' && (
          <RadioGroup
            name="status-form-outcome"
            legend="结束结果"
            options={ENDED_OUTCOMES.map((option) => ({ value: option.value, label: option.label }))}
            value={stage}
            onChange={(value) => setStage(value as Status)}
          />
        )}
        <DateField
          id="status-form-event-date"
          label={appliedSelected ? '确认提交日期' : '事件日期'}
          value={eventDate}
          onChange={handleEventDate}
          required
          testId="status-form-event-date"
        />
        {interviewSelected && (
          <div className="formRow">
            <DateField
              id="status-form-scheduled-date"
              label="面试日期"
              value={scheduledDate}
              onChange={handleScheduledDate}
              required
              testId="status-form-scheduled-date"
            />
            <TimeField
              id="status-form-scheduled-time"
              label="面试时间"
              value={scheduledTime}
              onChange={setScheduledTime}
              disabled={!scheduledDate}
              testId="status-form-scheduled-time"
            />
          </div>
        )}
        {interviewSelected && (
          <div className="formRow">
            <div className="formField">
              <label htmlFor="status-form-mode" className={cn('formLabel', 'formLabelOptional')}>
                面试方式（可选）
              </label>
              <select
                id="status-form-mode"
                className="formInput"
                value={mode}
                onChange={(event: ChangeEvent<HTMLSelectElement>) => setMode(event.target.value)}
              >
                <option value="">未选择</option>
                {MODE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="formField">
              <label htmlFor="status-form-location" className={cn('formLabel', 'formLabelOptional')}>
                面试地点/平台（可选）
              </label>
              <input
                id="status-form-location"
                className="formInput"
                value={location}
                onChange={(event) => setLocation(event.target.value)}
                maxLength={300}
              />
            </div>
          </div>
        )}
        {assessmentSelected && (
          <div className="formRow">
            <DateField
              id="status-form-assessment-scheduled-date"
              label="计划日期"
              value={scheduledDate}
              onChange={handleScheduledDate}
              testId="status-form-scheduled-date"
            />
            <TimeField
              id="status-form-assessment-scheduled-time"
              label="计划时间"
              value={scheduledTime}
              onChange={setScheduledTime}
              disabled={!scheduledDate}
              testId="status-form-scheduled-time"
            />
          </div>
        )}
        {assessmentSelected && (
          <div className="formRow">
            <DateField
              id="status-form-deadline-date"
              label="截止日期"
              value={deadlineDate}
              onChange={handleDeadlineDate}
              testId="status-form-deadline-date"
            />
            <TimeField
              id="status-form-deadline-time"
              label="截止时间"
              value={deadlineTime}
              onChange={setDeadlineTime}
              disabled={!deadlineDate}
              testId="status-form-deadline-time"
            />
          </div>
        )}
        {assessmentSelected && missingAssessmentDate && (
          <p className="formHint" data-testid="status-form-assessment-hint">
            请填写计划日期或截止日期（至少一项）。
          </p>
        )}
        {interviewSelected && missingInterviewDate && (
          <p className="formHint" data-testid="status-form-interview-hint">
            请填写面试日期。
          </p>
        )}
        {submitError && (
          <p className="formHint" role="alert" data-testid="status-form-error" style={{ color: 'var(--color-rejected)' }}>
            {submitError}
          </p>
        )}
        <div className="dialogActions">
          <button type="button" className="secondaryButton" onClick={onClose} disabled={pending}>
            取消
          </button>
          <button type="submit" className="flowButton" disabled={!canSubmit} data-testid="status-form-submit">
            {pending ? '更新中…' : '确认更新'}
          </button>
        </div>
      </form>
    </OverlayShell>
  )
}
