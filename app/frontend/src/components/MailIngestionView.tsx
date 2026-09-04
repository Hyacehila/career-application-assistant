import { useState, type FormEvent } from 'react'
import Check from 'lucide-react/dist/esm/icons/check'
import Mail from 'lucide-react/dist/esm/icons/mail'
import Pause from 'lucide-react/dist/esm/icons/pause'
import Play from 'lucide-react/dist/esm/icons/play'
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw'
import ShieldCheck from 'lucide-react/dist/esm/icons/shield-check'
import Unplug from 'lucide-react/dist/esm/icons/unplug'
import ConfirmDialog from './ConfirmDialog'
import { cn } from '../lib/classNames'
import { statusLabelOf } from '../lib/statuses'
import { useMailIngestion } from '../hooks/useMailIngestion'
import type {
  ApplicationRecord,
  ConnectMailPayload,
  HistoryWindow,
  LocalImapProvider,
  MailAccount,
  MailCandidate,
  MailProvider,
  ProposedMailStage,
} from '../api/client'
import styles from './MailIngestionView.module.css'

const PROVIDER_META: Record<MailProvider, { name: string; short: string; helpUrl?: string; helpLabel?: string }> = {
  outlook: {
    name: 'Outlook',
    short: 'O',
  },
  qq: {
    name: 'QQ 邮箱',
    short: 'QQ',
    helpUrl: 'https://hiflow.tencent.com/docs/applications/qq-mail/',
    helpLabel: '查看 QQ 邮箱授权码说明',
  },
  '163': {
    name: '163 邮箱',
    short: '163',
    helpUrl: 'https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac2ed007f2b27412aae',
    helpLabel: '查看网易邮箱授权密码说明',
  },
}

const HISTORY_OPTIONS: Array<{ value: HistoryWindow; label: string }> = [
  { value: 'new_only', label: '仅连接后的新邮件（推荐）' },
  { value: 'last_30_days', label: '回溯最近 30 天' },
  { value: 'last_90_days', label: '回溯最近 90 天' },
]

const STAGE_OPTIONS: Array<{ value: Exclude<ProposedMailStage, 'interview_unspecified'>; label: string }> = [
  { value: 'applied', label: '已投递' },
  { value: 'assessment', label: '笔试 / 测评' },
  { value: 'interview_1', label: '1面' },
  { value: 'interview_2', label: '2面' },
  { value: 'interview_3', label: '3面' },
  { value: 'interview_hr', label: 'HR面' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: '拒绝' },
  { value: 'withdrawn', label: '撤回' },
]

const ACCOUNT_STATUS_LABELS: Record<MailAccount['status'], string> = {
  disconnected: '未连接',
  connecting: '连接中',
  connected: '已连接',
  paused: '已暂停',
  needs_reauth: '需要重新授权',
  error: '连接异常',
}

const REVIEW_REASON_LABELS: Record<string, string> = {
  missing_match: '未匹配到投递记录',
  multiple_matches: '匹配到多条投递记录',
  missing_required_date: '缺少必要日期',
  ambiguous_date: '日期存在歧义',
  generic_interview: '需要选择面试轮次',
  manual_stage: '该阶段需要人工确认',
  low_confidence: '识别可信度不足',
  unsafe_transition: '与现有流程可能冲突',
  archived_application: '匹配记录已归档',
  conflicting_stages: '邮件中出现互相冲突的阶段',
  body_too_large: '邮件正文超过安全读取上限',
  body_missing: '邮件没有可解析的正文',
  encoding_fallback: '邮件编码需要人工复核',
  job_alert: '疑似职位订阅或推荐邮件',
}

export interface MailIngestionViewProps {
  onNotify: (message: string, tone?: 'success' | 'error') => void
  onEventCommitted: () => void
}

function formatTimestamp(value: string | null): string {
  if (!value) return '尚未同步'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function stageLabel(stage: ProposedMailStage | null): string {
  if (!stage) return '阶段待确认'
  if (stage === 'interview_unspecified') return '面试（轮次待确认）'
  return statusLabelOf(stage)
}

interface ProviderCardProps {
  account: MailAccount
  operationKind?: 'connect' | 'sync'
  busy: boolean
  onConnect: (provider: LocalImapProvider, body: ConnectMailPayload) => Promise<void>
  onSync: (provider: LocalImapProvider) => Promise<void>
  onPause: (provider: MailProvider) => Promise<void>
  onResume: (provider: MailProvider) => Promise<void>
  onDisconnectRequest: (provider: LocalImapProvider) => void
  onNotify: MailIngestionViewProps['onNotify']
}

function ProviderCard({
  account,
  operationKind,
  busy,
  onConnect,
  onSync,
  onPause,
  onResume,
  onDisconnectRequest,
  onNotify,
}: ProviderCardProps) {
  const meta = PROVIDER_META[account.provider]
  const isConnector = account.connection_mode === 'codex_connector'
  const imapProvider: LocalImapProvider | null = account.provider === 'outlook' ? null : account.provider
  const [editingConnection, setEditingConnection] = useState(false)
  const [historyWindow, setHistoryWindow] = useState<HistoryWindow>(account.history_window)
  const [mailboxAddress, setMailboxAddress] = useState('')
  const [authorizationCode, setAuthorizationCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const showConnectionForm = !isConnector && (account.status === 'disconnected'
    || account.status === 'needs_reauth'
    || account.status === 'error'
    || editingConnection)
  const operationLabel = operationKind === 'connect' ? '正在完成连接…' : operationKind === 'sync' ? '正在同步…' : null
  const actionBusy = busy || Boolean(operationKind) || account.status === 'connecting' || submitting

  const clearConnectionFields = () => {
    setMailboxAddress('')
    setAuthorizationCode('')
  }

  const cancelConnectionEdit = () => {
    clearConnectionFields()
    setHistoryWindow(account.history_window)
    setEditingConnection(false)
  }

  const requestDisconnect = () => {
    if (!imapProvider) return
    clearConnectionFields()
    setEditingConnection(false)
    onDisconnectRequest(imapProvider)
  }

  const handleConnect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (actionBusy || !imapProvider) return
    setSubmitting(true)
    const body: ConnectMailPayload = {
      mailbox_address: mailboxAddress.trim(),
      authorization_code: authorizationCode,
      history_window: historyWindow,
    }
    clearConnectionFields()
    try {
      await onConnect(imapProvider, body)
      setEditingConnection(false)
      onNotify(`${meta.name} 连接请求已启动`)
    } catch {
      // 安全错误由集中 hook 以固定文案呈现；表单不得回显授权码。
    } finally {
      setSubmitting(false)
    }
  }

  const runAction = async (action: () => Promise<void>, message: string) => {
    try {
      await action()
      onNotify(message)
    } catch {
      // 集中错误区会显示脱敏错误码。
    }
  }

  return (
    <article className={styles.providerCard} aria-labelledby={`mail-provider-${account.provider}`}>
      <div className={styles.providerHeading}>
        <span className={cn(styles.providerMark, styles[`providerMark_${account.provider}`])} aria-hidden="true">
          {meta.short}
        </span>
        <div className={styles.providerTitleBlock}>
          <h2 id={`mail-provider-${account.provider}`}>{meta.name}</h2>
          <p className={styles.maskedAddress}>
            {isConnector ? '由 Codex Outlook 连接器管理' : account.masked_address || '尚未绑定账号'}
          </p>
        </div>
        <span className={cn(styles.statusBadge, styles[`status_${account.status}`])} role="status" aria-live="polite">
          {operationLabel || (isConnector && account.status === 'disconnected'
            ? '等待新任务同步'
            : ACCOUNT_STATUS_LABELS[account.status])}
        </span>
      </div>

      <dl className={styles.accountFacts}>
        <div>
          <dt>上次成功同步</dt>
          <dd>{formatTimestamp(account.last_success_at)}</dd>
        </div>
        <div>
          <dt>待复核</dt>
          <dd>{account.pending_count} 条</dd>
        </div>
        {account.next_retry_at ? (
          <div>
            <dt>下次重试</dt>
            <dd>{formatTimestamp(account.next_retry_at)}</dd>
          </div>
        ) : null}
      </dl>

      {account.error_code ? <p className={styles.accountError}>错误码：{account.error_code}</p> : null}

      {isConnector ? (
        <div className={styles.connectForm}>
          <p className={styles.securityHint}>
            <ShieldCheck size={15} aria-hidden="true" />
            每个新的 Codex 任务会尝试一次只读同步；登录与权限由 Codex 连接器统一管理。
          </p>
          <div className={styles.accountActions}>
            {account.status === 'paused' ? (
              <button
                type="button"
                className="secondaryButton"
                onClick={() => runAction(() => onResume(account.provider), `${meta.name} 已恢复自动同步`)}
                disabled={actionBusy}
              >
                <Play size={15} aria-hidden="true" />
                恢复新任务同步
              </button>
            ) : (
              <button
                type="button"
                className="secondaryButton"
                onClick={() => runAction(() => onPause(account.provider), `${meta.name} 已暂停自动同步`)}
                disabled={actionBusy}
              >
                <Pause size={15} aria-hidden="true" />
                暂停新任务同步
              </button>
            )}
          </div>
        </div>
      ) : showConnectionForm ? (
        <form className={styles.connectForm} onSubmit={handleConnect} aria-label={`连接 ${meta.name}`}>
          <label className={styles.field}>
            <span>邮箱地址</span>
            <input
              type="email"
              autoComplete="off"
              value={mailboxAddress}
              onChange={(event) => setMailboxAddress(event.target.value)}
              placeholder={account.provider === 'qq' ? '例如：QQ 邮箱地址' : '例如：163 邮箱地址'}
              required
              disabled={actionBusy}
            />
          </label>
          <label className={styles.field}>
            <span>客户端授权码</span>
            <input
              type="password"
              autoComplete="off"
              value={authorizationCode}
              onChange={(event) => setAuthorizationCode(event.target.value)}
              placeholder="不是邮箱登录密码"
              required
              disabled={actionBusy}
            />
          </label>
          <label className={styles.field}>
            <span>首次读取范围</span>
            <select
              value={historyWindow}
              onChange={(event) => setHistoryWindow(event.target.value as HistoryWindow)}
              disabled={actionBusy}
            >
              {HISTORY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </label>
          <p className={styles.securityHint}>
            <ShieldCheck size={15} aria-hidden="true" />
            只读访问；凭据存入 Windows 安全凭据库，不写入看板数据库。
          </p>
          <div className={styles.formActions}>
            {meta.helpUrl && meta.helpLabel ? (
              <a href={meta.helpUrl} target="_blank" rel="noreferrer noopener">{meta.helpLabel}</a>
            ) : null}
            <div className={styles.formButtons}>
              {editingConnection ? (
                <button type="button" className="secondaryButton" onClick={cancelConnectionEdit}>
                  取消
                </button>
              ) : null}
              <button type="submit" className="primaryButton" disabled={actionBusy}>
                {actionBusy ? '处理中…' : account.status === 'disconnected' ? '连接邮箱' : '重新授权'}
              </button>
              {account.status !== 'disconnected' ? (
                <button
                  type="button"
                  className="dangerButton"
                  onClick={requestDisconnect}
                  disabled={actionBusy}
                >
                  断开
                </button>
              ) : null}
            </div>
          </div>
        </form>
      ) : (
        <div className={styles.accountActions}>
          <button
            type="button"
            className="secondaryButton"
            onClick={() => imapProvider
              ? runAction(() => onSync(imapProvider), `${meta.name} 同步已启动`)
              : Promise.resolve()}
            disabled={actionBusy || account.status !== 'connected'}
          >
            <RefreshCw size={15} aria-hidden="true" />
            立即同步
          </button>
          {account.status === 'paused' ? (
            <button
              type="button"
              className="secondaryButton"
              onClick={() => runAction(() => onResume(account.provider), `${meta.name} 已恢复同步`)}
              disabled={actionBusy}
            >
              <Play size={15} aria-hidden="true" />
              恢复
            </button>
          ) : (
            <button
              type="button"
              className="secondaryButton"
              onClick={() => runAction(() => onPause(account.provider), `${meta.name} 已暂停同步`)}
              disabled={actionBusy || account.status !== 'connected'}
            >
              <Pause size={15} aria-hidden="true" />
              暂停
            </button>
          )}
          <button type="button" className="secondaryButton" onClick={() => setEditingConnection(true)} disabled={actionBusy}>
            重新授权
          </button>
          <button
            type="button"
            className="dangerButton"
            onClick={requestDisconnect}
            disabled={actionBusy}
          >
            <Unplug size={15} aria-hidden="true" />
            断开
          </button>
        </div>
      )}
    </article>
  )
}

interface CandidateCardProps {
  candidate: MailCandidate
  applications: ApplicationRecord[]
  busy: boolean
  onConfirm: (
    id: number,
    body: {
      application_id: number
      stage: Exclude<ProposedMailStage, 'interview_unspecified'>
      scheduled_date: string | null
      scheduled_time: string | null
      deadline_date: string | null
      deadline_time: string | null
      timezone: string
      confirm_personally_submitted: boolean
    },
  ) => Promise<void>
  onDismissRequest: (candidate: MailCandidate) => void
}

function CandidateCard({ candidate, applications, busy, onConfirm, onDismissRequest }: CandidateCardProps) {
  const [applicationId, setApplicationId] = useState(candidate.matched_application_id ? String(candidate.matched_application_id) : '')
  const [stage, setStage] = useState<ProposedMailStage>(candidate.proposed_stage || 'interview_unspecified')
  const [scheduledDate, setScheduledDate] = useState(candidate.scheduled_date || '')
  const [scheduledTime, setScheduledTime] = useState(candidate.scheduled_time || '')
  const [deadlineDate, setDeadlineDate] = useState(candidate.deadline_date || '')
  const [deadlineTime, setDeadlineTime] = useState(candidate.deadline_time || '')
  const [personallySubmitted, setPersonallySubmitted] = useState(false)
  const isInterview = stage.startsWith('interview_')
  const missingApplication = applicationId === ''
  const missingInterviewDate = isInterview && scheduledDate === ''
  const needsAssessmentDate = stage === 'assessment' && scheduledDate === '' && deadlineDate === ''
  const invalidStage = stage === 'interview_unspecified'
  const invalidScheduledTime = scheduledDate !== '' && scheduledTime === '00:00'
  const invalidDeadlineTime = deadlineDate !== '' && deadlineTime === '00:00'
  const applicationErrorId = `mail-candidate-${candidate.id}-application-error`
  const stageErrorId = `mail-candidate-${candidate.id}-stage-error`
  const scheduleDateErrorId = `mail-candidate-${candidate.id}-schedule-date-error`
  const assessmentDateErrorId = `mail-candidate-${candidate.id}-assessment-date-error`
  const scheduleTimeErrorId = `mail-candidate-${candidate.id}-schedule-time-error`
  const deadlineTimeErrorId = `mail-candidate-${candidate.id}-deadline-time-error`
  const cannotConfirm = busy
    || missingApplication
    || invalidStage
    || missingInterviewDate
    || needsAssessmentDate
    || (stage === 'applied' && !personallySubmitted)
    || ((isInterview || stage === 'assessment') && invalidScheduledTime)
    || (stage === 'assessment' && invalidDeadlineTime)
  const confidence = Math.max(0, Math.min(100, Math.round(candidate.confidence)))

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (cannotConfirm) return
    const includesSchedule = isInterview || stage === 'assessment'
    const includesDeadline = stage === 'assessment'
    await onConfirm(candidate.id, {
      application_id: Number(applicationId),
      stage,
      scheduled_date: includesSchedule && scheduledDate ? scheduledDate : null,
      scheduled_time: includesSchedule && scheduledDate && scheduledTime ? scheduledTime : null,
      deadline_date: includesDeadline && deadlineDate ? deadlineDate : null,
      deadline_time: includesDeadline && deadlineDate && deadlineTime ? deadlineTime : null,
      timezone: candidate.timezone || 'Asia/Shanghai',
      confirm_personally_submitted: stage === 'applied' && personallySubmitted,
    })
  }

  return (
    <article className={styles.candidateCard} aria-labelledby={`mail-candidate-${candidate.id}`}>
      <div className={styles.candidateSummary}>
        <div>
          <p className={styles.providerEyebrow}>{PROVIDER_META[candidate.provider].name}</p>
          <h3 id={`mail-candidate-${candidate.id}`}>
            {candidate.company_name || '公司待确认'}
            <span aria-hidden="true"> · </span>
            {candidate.job_title || '岗位待确认'}
          </h3>
          <p className={styles.candidateMeta}>
            建议阶段：{stageLabel(candidate.proposed_stage)} · 邮件事件日期：{candidate.event_date || '待确认'}
          </p>
        </div>
        <div className={styles.confidenceBlock}>
          <span>可信度</span>
          <strong>{confidence}%</strong>
          <div
            className={styles.confidenceTrack}
            role="meter"
            aria-label="识别可信度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={confidence}
          >
            <span style={{ width: `${confidence}%` }} />
          </div>
        </div>
      </div>

      {candidate.review_reasons.length > 0 ? (
        <ul className={styles.reasonList} aria-label="需要复核的原因">
          {candidate.review_reasons.map((reason) => (
            <li key={reason}>{REVIEW_REASON_LABELS[reason] || reason}</li>
          ))}
        </ul>
      ) : null}

      <form className={styles.candidateForm} onSubmit={(event) => { void handleSubmit(event).catch(() => undefined) }}>
        <label className={cn(styles.field, styles.fieldWide)}>
          <span>匹配投递记录</span>
          <select
            value={applicationId}
            onChange={(event) => setApplicationId(event.target.value)}
            required
            disabled={busy}
            aria-invalid={missingApplication}
            aria-describedby={missingApplication ? applicationErrorId : undefined}
          >
            <option value="">请选择唯一记录</option>
            {applications.map((application) => (
              <option key={application.id} value={application.id}>
                #{application.id} · {application.company_name} · {application.job_title}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          <span>确认阶段</span>
          <select
            value={stage}
            onChange={(event) => setStage(event.target.value as ProposedMailStage)}
            disabled={busy}
            aria-invalid={invalidStage}
            aria-describedby={invalidStage ? stageErrorId : undefined}
          >
            {!candidate.proposed_stage || candidate.proposed_stage === 'interview_unspecified'
              ? <option value="interview_unspecified">请选择面试轮次</option>
              : null}
            {STAGE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>

        {isInterview || stage === 'assessment' ? (
          <>
            <label className={styles.field}>
              <span>{isInterview ? '面试日期' : '计划日期'}</span>
              <input
                type="date"
                value={scheduledDate}
                onChange={(event) => setScheduledDate(event.target.value)}
                disabled={busy}
                aria-invalid={missingInterviewDate || needsAssessmentDate}
                aria-describedby={missingInterviewDate
                  ? scheduleDateErrorId
                  : needsAssessmentDate ? assessmentDateErrorId : undefined}
              />
            </label>
            <label className={styles.field}>
              <span>计划时间（可选）</span>
              <input
                type="time"
                min="00:01"
                value={scheduledTime}
                onChange={(event) => setScheduledTime(event.target.value)}
                disabled={busy || !scheduledDate}
                aria-invalid={invalidScheduledTime}
                aria-describedby={invalidScheduledTime ? scheduleTimeErrorId : undefined}
              />
            </label>
          </>
        ) : null}

        {stage === 'assessment' ? (
          <>
            <label className={styles.field}>
              <span>截止日期</span>
              <input
                type="date"
                value={deadlineDate}
                onChange={(event) => setDeadlineDate(event.target.value)}
                disabled={busy}
                aria-invalid={needsAssessmentDate}
                aria-describedby={needsAssessmentDate ? assessmentDateErrorId : undefined}
              />
            </label>
            <label className={styles.field}>
              <span>截止时间（可选）</span>
              <input
                type="time"
                min="00:01"
                value={deadlineTime}
                onChange={(event) => setDeadlineTime(event.target.value)}
                disabled={busy || !deadlineDate}
                aria-invalid={invalidDeadlineTime}
                aria-describedby={invalidDeadlineTime ? deadlineTimeErrorId : undefined}
              />
            </label>
          </>
        ) : null}

        {stage === 'applied' ? (
          <label className={cn('formConfirmation', styles.personalConfirmation)}>
            <input
              type="checkbox"
              checked={personallySubmitted}
              onChange={(event) => setPersonallySubmitted(event.target.checked)}
              disabled={busy}
              required
            />
            我确认已亲自完成最终投递
          </label>
        ) : null}

        {missingApplication ? <p id={applicationErrorId} className={styles.validationHint}>请选择唯一的投递记录。</p> : null}
        {invalidStage ? <p id={stageErrorId} className={styles.validationHint}>请选择明确的面试轮次。</p> : null}
        {missingInterviewDate ? <p id={scheduleDateErrorId} className={styles.validationHint}>面试日期必填。</p> : null}
        {needsAssessmentDate ? <p id={assessmentDateErrorId} className={styles.validationHint}>计划日期或截止日期至少填写一项。</p> : null}
        {invalidScheduledTime ? <p id={scheduleTimeErrorId} className={styles.validationHint}>计划时间不能使用 00:00；未知时间请留空。</p> : null}
        {invalidDeadlineTime ? <p id={deadlineTimeErrorId} className={styles.validationHint}>截止时间不能使用 00:00；未知时间请留空。</p> : null}
        <div className={styles.candidateActions}>
          <p>时区：{candidate.timezone || 'Asia/Shanghai'} · 候选保留至 {candidate.expires_at?.slice(0, 10) || '未提供'}</p>
          <div>
            <button type="button" className="secondaryButton" disabled={busy} onClick={() => onDismissRequest(candidate)}>
              忽略
            </button>
            <button type="submit" className="flowButton" disabled={cannotConfirm}>
              <Check size={15} aria-hidden="true" />
              {busy ? '处理中…' : '确认写入时间线'}
            </button>
          </div>
        </div>
      </form>
    </article>
  )
}

export default function MailIngestionView({ onNotify, onEventCommitted }: MailIngestionViewProps) {
  const mail = useMailIngestion(true)
  const [disconnectTarget, setDisconnectTarget] = useState<LocalImapProvider | null>(null)
  const [dismissTarget, setDismissTarget] = useState<MailCandidate | null>(null)

  const handleConfirmCandidate = async (
    id: number,
    body: Parameters<typeof mail.confirmCandidate>[1],
  ) => {
    try {
      await mail.confirmCandidate(id, body)
      onEventCommitted()
      onNotify('邮件事件已写入时间线')
    } catch {
      // 集中错误区展示固定文案和错误码。
    }
  }

  return (
    <section className={styles.page} aria-labelledby="mail-ingestion-title">
      <div className={styles.hero}>
        <div>
          <p className={styles.kicker}><Mail size={16} aria-hidden="true" /> 自动读取 · 只读模式</p>
          <h1 id="mail-ingestion-title">邮箱接入</h1>
          <p className={styles.intro}>增量识别招聘通知，只保存结构化投递事件。这里不是收件箱，也不会发送或标记邮件。</p>
        </div>
        <div className={styles.pendingSummary} aria-label="待人工复核总数">
          <strong>{mail.pendingCount}</strong>
          <span>待人工复核</span>
        </div>
      </div>

      {mail.error ? (
        <div className={styles.errorBanner} role="alert">
          <div>
            <strong>{mail.error.message}</strong>
            <span>错误码：{mail.error.code}</span>
          </div>
          <div>
            <button type="button" className="secondaryButton" onClick={mail.clearError}>关闭</button>
            <button type="button" className="primaryButton" onClick={mail.refetch}>重新加载</button>
          </div>
        </div>
      ) : null}

      {mail.loading ? <p className={styles.loadingLine} role="status">正在安全地读取连接状态…</p> : null}

      {mail.accountsLoaded ? (
        <div className={styles.providerGrid} aria-label="邮箱提供商">
          {mail.accounts.map((account) => (
            <ProviderCard
              key={`${account.provider}:${account.history_window}`}
              account={account}
              operationKind={mail.activeOperations[account.provider]?.kind}
              busy={mail.busyProviders.has(account.provider)}
              onConnect={mail.connect}
              onSync={mail.sync}
              onPause={mail.pause}
              onResume={mail.resume}
              onDisconnectRequest={setDisconnectTarget}
              onNotify={onNotify}
            />
          ))}
        </div>
      ) : (
        <div className={styles.providerUnavailable} role="status">
          <ShieldCheck size={24} aria-hidden="true" />
          <strong>{mail.loading ? '正在确认邮箱连接状态…' : '无法确认邮箱连接状态'}</strong>
          <span>连接状态确认前不会显示或提交任何邮箱凭据。</span>
        </div>
      )}

      <section className={styles.reviewSection} aria-labelledby="mail-review-title">
        <div className={styles.reviewHeading}>
          <div>
            <p className={styles.sectionEyebrow}>结构化结果</p>
            <h2 id="mail-review-title">待人工复核</h2>
          </div>
          <button type="button" className="secondaryButton" onClick={mail.refetch} disabled={mail.loading}>
            <RefreshCw size={15} aria-hidden="true" />
            刷新
          </button>
        </div>

        {mail.candidates.length === 0 && !mail.loading ? (
          <div className={styles.emptyReview}>
            <ShieldCheck size={28} aria-hidden="true" />
            <strong>没有待复核事件</strong>
            <span>新招聘通知会在完成结构化提取后出现在这里，不会展示邮件原文。</span>
          </div>
        ) : (
          <div className={styles.candidateList}>
            {mail.candidates.map((candidate) => (
              <CandidateCard
                key={candidate.id}
                candidate={candidate}
                applications={mail.applications}
                busy={mail.busyCandidates.has(candidate.id)}
                onConfirm={handleConfirmCandidate}
                onDismissRequest={setDismissTarget}
              />
            ))}
          </div>
        )}
      </section>

      {disconnectTarget ? (
        <ConfirmDialog
          title={`断开 ${PROVIDER_META[disconnectTarget].name}`}
          message="将删除此邮箱的本机授权码凭据和同步游标；已写入的结构化时间线记录会保留。"
          confirmLabel="确认断开"
          danger
          onConfirm={() => mail.disconnect(disconnectTarget)}
          onDone={() => {
            onNotify(`${PROVIDER_META[disconnectTarget].name} 已断开`)
            setDisconnectTarget(null)
          }}
          onClose={() => setDisconnectTarget(null)}
        />
      ) : null}

      {dismissTarget ? (
        <ConfirmDialog
          title="忽略这条邮件事件"
          message="忽略后，该结构化候选不再出现在待复核列表；邮件原文从未保存。"
          confirmLabel="确认忽略"
          onConfirm={() => mail.dismissCandidate(dismissTarget.id)}
          onDone={() => {
            onNotify('已忽略邮件事件')
            setDismissTarget(null)
          }}
          onClose={() => setDismissTarget(null)}
        />
      ) : null}
    </section>
  )
}
