import { useMemo, useState } from 'react'
import type { ChangeEvent, FormEvent, ReactNode } from 'react'
import { APPLICATION_TYPES, createApplication, patchApplication, type ApplicationRecord } from '../api/client'
import { cn } from '../lib/classNames'
import { todayDate } from '../lib/dates'
import OverlayShell from './OverlayShell'

export interface RecordFormPrefill {
  company_name?: string
  job_title?: string
}

export interface RecordFormDialogProps {
  mode: 'create' | 'edit'
  record?: ApplicationRecord | null
  prefill?: RecordFormPrefill
  onDone?: () => void
  onError?: (message: string) => void
  onClose: () => void
}

interface FormValues {
  company_name: string
  job_title: string
  department: string
  job_code: string
  application_type: string
  location: string
  source: string
  job_url: string
  next_action: string
  next_action_date: string
  notes: string
}

function FormField({
  id,
  label,
  required,
  children,
}: {
  id: string
  label: string
  required?: boolean
  children: ReactNode
}) {
  return (
    <div className="formField">
      <label htmlFor={id} className={cn('formLabel', required && 'formLabelRequired')}>
        {label}
        {required ? '（必填）' : <span className="formLabelOptional">（可选）</span>}
      </label>
      {children}
    </div>
  )
}

export default function RecordFormDialog({
  mode,
  record,
  prefill,
  onDone,
  onError,
  onClose,
}: RecordFormDialogProps) {
  const initialValues = useMemo<FormValues>(() => {
    if (mode === 'edit' && record) {
      return {
        company_name: record.company_name,
        job_title: record.job_title,
        department: record.department ?? '',
        job_code: record.job_code ?? '',
        application_type: record.application_type ?? '',
        location: record.location ?? '',
        source: record.source ?? '',
        job_url: record.job_url ?? '',
        next_action: record.next_action ?? '',
        next_action_date: record.next_action_date ?? '',
        notes: record.notes ?? '',
      }
    }
    return {
      company_name: prefill?.company_name ?? '',
      job_title: prefill?.job_title ?? '',
      department: '',
      job_code: '',
      application_type: '',
      location: '',
      source: '',
      job_url: '',
      next_action: '',
      next_action_date: '',
      notes: '',
    }
  }, [mode, record, prefill])

  const [values, setValues] = useState<FormValues>(initialValues)
  const [pending, setPending] = useState(false)

  const title = mode === 'create' ? '新增记录' : '编辑记录'
  const companyValid = values.company_name.trim() !== ''
  const jobValid = values.job_title.trim() !== ''
  const canSubmit = companyValid && jobValid && !pending

  const handleChange =
    (key: keyof FormValues) =>
    (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
      setValues((previous) => ({ ...previous, [key]: event.target.value }))
    }

  const buildBody = () => ({
    company_name: values.company_name.trim(),
    job_title: values.job_title.trim(),
    department: values.department.trim() || null,
    job_code: values.job_code.trim() || null,
    application_type: values.application_type || null,
    location: values.location.trim() || null,
    source: values.source.trim() || null,
    job_url: values.job_url.trim() || null,
    next_action: values.next_action.trim() || null,
    next_action_date: values.next_action_date || null,
    notes: values.notes.trim() || null,
  })

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return
    setPending(true)
    try {
      if (mode === 'create') {
        await createApplication({ ...buildBody(), event_date: todayDate() })
      } else if (record) {
        await patchApplication(record.id, buildBody())
      }
      onDone?.()
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : '保存失败，请稍后重试'
      onError?.(message)
      setPending(false)
    }
  }

  return (
    <OverlayShell title={title} onClose={onClose}>
      <form className="formStack" onSubmit={handleSubmit}>
        <FormField id="record-company" label="公司" required>
          <input
            id="record-company"
            className="formInput"
            value={values.company_name}
            onChange={handleChange('company_name')}
            maxLength={200}
            placeholder="示例科技"
            data-testid="record-form-company"
          />
        </FormField>
        <FormField id="record-job" label="岗位" required>
          <input
            id="record-job"
            className="formInput"
            value={values.job_title}
            onChange={handleChange('job_title')}
            maxLength={200}
            placeholder="前端工程师"
            data-testid="record-form-job"
          />
        </FormField>
        <div className="formRow">
          <FormField id="record-department" label="部门">
            <input
              id="record-department"
              className="formInput"
              value={values.department}
              onChange={handleChange('department')}
              maxLength={100}
            />
          </FormField>
          <FormField id="record-job-code" label="岗位编号">
            <input
              id="record-job-code"
              className="formInput"
              value={values.job_code}
              onChange={handleChange('job_code')}
              maxLength={100}
            />
          </FormField>
        </div>
        <div className="formRow">
          <FormField id="record-next-action" label="下一步事项">
            <input
              id="record-next-action"
              className="formInput"
              value={values.next_action}
              onChange={handleChange('next_action')}
              maxLength={500}
              placeholder="例如：准备技术面试"
              data-testid="record-form-next-action"
            />
          </FormField>
          <FormField id="record-next-action-date" label="下一步日期">
            <input
              id="record-next-action-date"
              className="formInput"
              type="date"
              value={values.next_action_date}
              onChange={handleChange('next_action_date')}
              data-testid="record-form-next-action-date"
            />
          </FormField>
        </div>
        <FormField id="record-notes" label="结构化备注">
          <textarea
            id="record-notes"
            className="formInput formTextArea"
            value={values.notes}
            onChange={handleChange('notes')}
            maxLength={1000}
            rows={3}
            placeholder="仅记录必要的流程信息，不粘贴邮件正文或个人资料"
            data-testid="record-form-notes"
          />
        </FormField>
        <div className="formRow">
          <FormField id="record-type" label="投递类型">
            <select
              id="record-type"
              className="formInput"
              value={values.application_type}
              onChange={handleChange('application_type')}
            >
              <option value="">未填写</option>
              {APPLICATION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </FormField>
          <FormField id="record-location" label="地点">
            <input
              id="record-location"
              className="formInput"
              value={values.location}
              onChange={handleChange('location')}
              maxLength={200}
            />
          </FormField>
        </div>
        <div className="formRow">
          <FormField id="record-source" label="来源">
            <input
              id="record-source"
              className="formInput"
              value={values.source}
              onChange={handleChange('source')}
              maxLength={100}
            />
          </FormField>
          <FormField id="record-job-url" label="岗位网址">
            <input
              id="record-job-url"
              className="formInput"
              type="url"
              value={values.job_url}
              onChange={handleChange('job_url')}
              maxLength={2000}
            />
          </FormField>
        </div>
        {mode === 'create' && <p className="formHint">新增记录默认进入“待确认投递”，状态只能通过后续事件更新。</p>}
        {mode === 'edit' && <p className="formHint">这里只能修改岗位元数据；状态变化请使用“更新状态”。</p>}
        <div className="dialogActions">
          <button type="button" className="secondaryButton" onClick={onClose} disabled={pending}>
            取消
          </button>
          <button type="submit" className="primaryButton" disabled={!canSubmit} data-testid="record-form-submit">
            {pending ? '保存中…' : mode === 'create' ? '创建记录' : '保存修改'}
          </button>
        </div>
      </form>
    </OverlayShell>
  )
}
