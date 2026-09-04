import { useCallback, useEffect, useState } from 'react'
import {
  APIError,
  confirmMailCandidate,
  connectMailAccount,
  disconnectMailAccount,
  dismissMailCandidate,
  getMailOperation,
  listAllApplications,
  listMailAccounts,
  listMailCandidates,
  pauseMailAccount,
  resumeMailAccount,
  syncMailAccount,
  type ApplicationRecord,
  type ConfirmMailCandidatePayload,
  type ConnectMailPayload,
  type ConfirmMailCandidateResponse,
  type MailAccount,
  type MailCandidate,
  type MailOperationKind,
  type MailProvider,
  type LocalImapProvider,
} from '../api/client'

const OPERATION_POLL_MS = 1_500
const CONNECTING_STATUS_POLL_MS = 2_500
const MAX_OPERATION_POLL_FAILURES = 3
const PROVIDERS: MailProvider[] = ['outlook', 'qq', '163']

interface ActiveOperation {
  id: string
  kind: MailOperationKind
  failures: number
}

export interface MailQueryError {
  code: string
  message: string
}

export interface MailIngestionResult {
  accounts: MailAccount[]
  candidates: MailCandidate[]
  applications: ApplicationRecord[]
  pendingCount: number
  accountsLoaded: boolean
  loading: boolean
  error: MailQueryError | null
  activeOperations: Partial<Record<MailProvider, ActiveOperation>>
  busyProviders: ReadonlySet<MailProvider>
  busyCandidates: ReadonlySet<number>
  refetch: () => void
  clearError: () => void
  connect: (provider: LocalImapProvider, body: ConnectMailPayload) => Promise<void>
  sync: (provider: LocalImapProvider) => Promise<void>
  pause: (provider: MailProvider) => Promise<void>
  resume: (provider: MailProvider) => Promise<void>
  disconnect: (provider: LocalImapProvider) => Promise<void>
  confirmCandidate: (id: number, body: ConfirmMailCandidatePayload) => Promise<ConfirmMailCandidateResponse>
  dismissCandidate: (id: number) => Promise<void>
}

function safeError(error: unknown, action: string): MailQueryError {
  const code = error instanceof APIError ? error.code : 'request_failed'
  return {
    code,
    message: `${action}失败。凭据和邮件内容不会在此处显示，请根据错误码重试。`,
  }
}

function disconnectedAccount(provider: MailProvider): MailAccount {
  return {
    provider,
    connection_mode: provider === 'outlook' ? 'codex_connector' : 'local_imap',
    status: 'disconnected',
    masked_address: null,
    history_window: 'new_only',
    last_attempt_at: null,
    last_success_at: null,
    next_retry_at: null,
    error_code: null,
    pending_count: 0,
  }
}

function orderedAccounts(items: MailAccount[]): MailAccount[] {
  const byProvider = new Map(items.map((item) => [item.provider, item]))
  return PROVIDERS.map((provider) => byProvider.get(provider) ?? disconnectedAccount(provider))
}

export function useMailIngestion(enabled: boolean): MailIngestionResult {
  const [accounts, setAccounts] = useState<MailAccount[]>(() => orderedAccounts([]))
  const [candidates, setCandidates] = useState<MailCandidate[]>([])
  const [applications, setApplications] = useState<ApplicationRecord[]>([])
  const [pendingCount, setPendingCount] = useState(0)
  const [accountsLoaded, setAccountsLoaded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<MailQueryError | null>(null)
  const [tick, setTick] = useState(0)
  const [activeOperations, setActiveOperations] = useState<Partial<Record<MailProvider, ActiveOperation>>>({})
  const [busyProviders, setBusyProviders] = useState<Set<MailProvider>>(() => new Set())
  const [busyCandidates, setBusyCandidates] = useState<Set<number>>(() => new Set())

  const refetch = useCallback(() => setTick((value) => value + 1), [])
  const clearError = useCallback(() => setError(null), [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const controller = new AbortController()
    setLoading(true)
    Promise.allSettled([
      listMailAccounts(controller.signal),
      listMailCandidates('pending', controller.signal),
      listAllApplications({ sort: '-updated_at', signal: controller.signal }),
    ]).then(([accountResult, candidateResult, applicationResult]) => {
      if (controller.signal.aborted) return
      const failures: unknown[] = []
      if (accountResult.status === 'fulfilled') {
        setAccounts(orderedAccounts(accountResult.value.items))
        setPendingCount(accountResult.value.pending_count)
        setAccountsLoaded(true)
      } else {
        failures.push(accountResult.reason)
      }
      if (candidateResult.status === 'fulfilled') {
        setCandidates(candidateResult.value.items)
      } else {
        failures.push(candidateResult.reason)
      }
      if (applicationResult.status === 'fulfilled') {
        setApplications(applicationResult.value.items)
      } else {
        failures.push(applicationResult.reason)
      }
      setError(failures.length > 0 ? safeError(failures[0], '加载邮箱接入状态') : null)
      setLoading(false)
    })
    return () => controller.abort()
  }, [enabled, tick])

  useEffect(() => {
    const entries = Object.entries(activeOperations) as Array<[MailProvider, ActiveOperation]>
    if (!enabled || entries.length === 0) return
    const controller = new AbortController()
    let timer: number | null = null
    let stopped = false

    const poll = async () => {
      const results = await Promise.all(entries.map(async ([provider, active]) => {
        try {
          return { provider, active, operation: await getMailOperation(active.id, controller.signal) }
        } catch (pollError) {
          return { provider, active, pollError }
        }
      }))
      if (stopped) return

      const completed = new Set<MailProvider>()
      const retryCounts = new Map<MailProvider, number>()
      let shouldRefresh = false
      for (const result of results) {
        if ('pollError' in result) {
          if (controller.signal.aborted) continue
          const failures = result.active.failures + 1
          const missingOperation = result.pollError instanceof APIError
            && (result.pollError.status === 404 || result.pollError.code === 'mail_operation_not_found')
          if (missingOperation || failures >= MAX_OPERATION_POLL_FAILURES) {
            completed.add(result.provider)
            shouldRefresh = true
            setError({
              code: missingOperation ? 'mail_operation_not_found' : 'mail_operation_status_unavailable',
              message: '无法继续确认邮箱操作状态，已停止自动轮询并刷新账户状态。',
            })
          } else {
            retryCounts.set(result.provider, failures)
          }
          continue
        }
        const { provider, operation, active } = result
        if (operation.status !== 'succeeded' && operation.status !== 'failed') {
          if (active.failures > 0) retryCounts.set(provider, 0)
          continue
        }
        completed.add(provider)
        shouldRefresh = true
        if (operation.status === 'failed') {
          setError({
            code: operation.error_code || 'mail_operation_failed',
            message: '邮箱操作未完成。凭据和邮件内容不会在此处显示，请根据错误码重试。',
          })
        }
      }

      if (completed.size > 0 || retryCounts.size > 0) {
        setActiveOperations((current) => {
          const next = { ...current }
          for (const provider of completed) delete next[provider]
          for (const [provider, failures] of retryCounts) {
            const active = next[provider]
            if (active) next[provider] = { ...active, failures }
          }
          return next
        })
      }
      if (shouldRefresh) refetch()
      if (completed.size < entries.length) timer = window.setTimeout(poll, OPERATION_POLL_MS)
    }

    timer = window.setTimeout(poll, OPERATION_POLL_MS)
    return () => {
      stopped = true
      controller.abort()
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [activeOperations, enabled, refetch])

  useEffect(() => {
    if (!enabled || !accountsLoaded) return
    const needsRecovery = accounts.some((account) => (
      account.status === 'connecting' && activeOperations[account.provider] === undefined
    ))
    if (!needsRecovery) return
    const timer = window.setTimeout(refetch, CONNECTING_STATUS_POLL_MS)
    return () => window.clearTimeout(timer)
  }, [accounts, accountsLoaded, activeOperations, enabled, refetch, tick])

  const markProviderBusy = useCallback((provider: MailProvider, busy: boolean) => {
    setBusyProviders((current) => {
      const next = new Set(current)
      if (busy) next.add(provider)
      else next.delete(provider)
      return next
    })
  }, [])

  const replaceAccount = useCallback((account: MailAccount) => {
    setAccounts((current) => orderedAccounts(current.filter((item) => item.provider !== account.provider).concat(account)))
  }, [])

  const connect = useCallback(async (provider: LocalImapProvider, body: ConnectMailPayload) => {
    markProviderBusy(provider, true)
    setError(null)
    try {
      const accepted = await connectMailAccount(provider, body)
      setActiveOperations((current) => ({
        ...current,
        [provider]: { id: accepted.operation_id, kind: 'connect', failures: 0 },
      }))
      setAccounts((current) => current.map((account) => (
        account.provider === provider ? { ...account, status: 'connecting', error_code: null } : account
      )))
    } catch (requestError) {
      setError(safeError(requestError, '启动邮箱连接'))
      throw requestError
    } finally {
      markProviderBusy(provider, false)
    }
  }, [markProviderBusy])

  const sync = useCallback(async (provider: LocalImapProvider) => {
    markProviderBusy(provider, true)
    setError(null)
    try {
      const accepted = await syncMailAccount(provider)
      setActiveOperations((current) => ({
        ...current,
        [provider]: { id: accepted.operation_id, kind: 'sync', failures: 0 },
      }))
    } catch (requestError) {
      setError(safeError(requestError, '启动同步'))
      throw requestError
    } finally {
      markProviderBusy(provider, false)
    }
  }, [markProviderBusy])

  const runImmediateAccountAction = useCallback(async (
    provider: MailProvider,
    actionName: string,
    action: () => Promise<MailAccount>,
  ) => {
    markProviderBusy(provider, true)
    setError(null)
    try {
      replaceAccount(await action())
    } catch (requestError) {
      setError(safeError(requestError, actionName))
      throw requestError
    } finally {
      markProviderBusy(provider, false)
    }
  }, [markProviderBusy, replaceAccount])

  const pause = useCallback(
    (provider: MailProvider) => runImmediateAccountAction(provider, '暂停邮箱同步', () => pauseMailAccount(provider)),
    [runImmediateAccountAction],
  )
  const resume = useCallback(
    (provider: MailProvider) => runImmediateAccountAction(provider, '恢复邮箱同步', () => resumeMailAccount(provider)),
    [runImmediateAccountAction],
  )

  const disconnect = useCallback(async (provider: LocalImapProvider) => {
    markProviderBusy(provider, true)
    setError(null)
    try {
      await disconnectMailAccount(provider)
      setAccounts((current) => current.map((account) => (
        account.provider === provider
          ? {
              ...disconnectedAccount(provider),
              history_window: account.history_window,
              pending_count: account.pending_count,
            }
          : account
      )))
      setActiveOperations((current) => {
        const next = { ...current }
        delete next[provider]
        return next
      })
      refetch()
    } catch (requestError) {
      setError(safeError(requestError, '断开邮箱'))
      throw requestError
    } finally {
      markProviderBusy(provider, false)
    }
  }, [markProviderBusy, refetch])

  const markCandidateBusy = useCallback((id: number, busy: boolean) => {
    setBusyCandidates((current) => {
      const next = new Set(current)
      if (busy) next.add(id)
      else next.delete(id)
      return next
    })
  }, [])

  const removeCandidate = useCallback((id: number, provider?: MailProvider) => {
    setCandidates((current) => current.filter((candidate) => candidate.id !== id))
    setPendingCount((current) => Math.max(0, current - 1))
    setAccounts((current) => current.map((account) => (
      account.provider === provider && account.pending_count > 0
        ? { ...account, pending_count: account.pending_count - 1 }
        : account
    )))
  }, [])

  const confirmCandidate = useCallback(async (id: number, body: ConfirmMailCandidatePayload) => {
    const provider = candidates.find((candidate) => candidate.id === id)?.provider
    markCandidateBusy(id, true)
    setError(null)
    try {
      const response = await confirmMailCandidate(id, body)
      removeCandidate(id, provider)
      return response
    } catch (requestError) {
      setError(safeError(requestError, '确认邮件事件'))
      throw requestError
    } finally {
      markCandidateBusy(id, false)
    }
  }, [candidates, markCandidateBusy, removeCandidate])

  const dismissCandidate = useCallback(async (id: number) => {
    const provider = candidates.find((candidate) => candidate.id === id)?.provider
    markCandidateBusy(id, true)
    setError(null)
    try {
      await dismissMailCandidate(id)
      removeCandidate(id, provider)
    } catch (requestError) {
      setError(safeError(requestError, '忽略邮件事件'))
      throw requestError
    } finally {
      markCandidateBusy(id, false)
    }
  }, [candidates, markCandidateBusy, removeCandidate])

  return {
    accounts,
    candidates,
    applications,
    pendingCount,
    accountsLoaded,
    loading,
    error,
    activeOperations,
    busyProviders,
    busyCandidates,
    refetch,
    clearError,
    connect,
    sync,
    pause,
    resume,
    disconnect,
    confirmCandidate,
    dismissCandidate,
  }
}
