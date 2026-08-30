import { useEffect, useMemo, useRef, useState } from 'react'
import AppShell from './components/AppShell'
import BoardView from './components/BoardView'
import ConfirmDialog from './components/ConfirmDialog'
import DetailDrawer from './components/DetailDrawer'
import MailIngestionView from './components/MailIngestionView'
import RecordFormDialog from './components/RecordFormDialog'
import StatusFormDialog, { type StatusFormTarget } from './components/StatusFormDialog'
import TableView from './components/TableView'
import { ToastViewport, useToasts } from './components/Toast'
import { postEvent, resetDemo, type ApplicationRecord } from './api/client'
import { useBoardQuery } from './hooks/useBoardQuery'
import { useServiceHealth } from './hooks/useServiceHealth'
import { useUrlState, type ViewName } from './hooks/useUrlState'
import { todayDate } from './lib/dates'
import type { BoardGroup } from './lib/statuses'

const SEARCH_DEBOUNCE_MS = 300

interface StatusTargetState {
  record: ApplicationRecord
  target: StatusFormTarget
}

export default function App() {
  const [urlState, updateUrlState] = useUrlState()
  const serviceHealth = useServiceHealth()
  const isDemo = serviceHealth.data?.mode === 'demo'
  const mailAvailable = serviceHealth.data?.mail_ingestion === true && !isDemo
  const effectiveView: ViewName = urlState.view === 'mail' && !mailAvailable ? 'board' : urlState.view
  const boardUrlState = useMemo(
    () => effectiveView === urlState.view ? urlState : { ...urlState, view: effectiveView },
    [effectiveView, urlState],
  )
  const [searchDraft, setSearchDraft] = useState(urlState.q)
  const searchTimer = useRef<number | null>(null)
  const boardQuery = useBoardQuery(boardUrlState, effectiveView !== 'mail')

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [recordFormOpen, setRecordFormOpen] = useState(false)
  const [editingRecord, setEditingRecord] = useState<ApplicationRecord | null>(null)
  const [statusTarget, setStatusTarget] = useState<StatusTargetState | null>(null)
  const [confirmAppliedRecord, setConfirmAppliedRecord] = useState<ApplicationRecord | null>(null)
  const [detailVersion, setDetailVersion] = useState(0)
  const [demoResetting, setDemoResetting] = useState(false)
  const { toasts, showToast } = useToasts()

  useEffect(() => {
    setSearchDraft(urlState.q)
  }, [urlState.q])

  useEffect(() => {
    if (serviceHealth.data && urlState.view === 'mail' && !mailAvailable) {
      updateUrlState({ view: 'board' })
    }
  }, [mailAvailable, serviceHealth.data, updateUrlState, urlState.view])

  useEffect(
    () => () => {
      if (searchTimer.current !== null) {
        window.clearTimeout(searchTimer.current)
      }
    },
    [],
  )

  const handleSearchChange = (value: string) => {
    setSearchDraft(value)
    if (searchTimer.current !== null) {
      window.clearTimeout(searchTimer.current)
    }
    searchTimer.current = window.setTimeout(() => {
      updateUrlState({ q: value })
    }, SEARCH_DEBOUNCE_MS)
  }

  const handleSearchSubmit = () => {
    if (searchTimer.current !== null) {
      window.clearTimeout(searchTimer.current)
      searchTimer.current = null
    }
    updateUrlState({ q: searchDraft })
  }

  const handleViewChange = (view: ViewName) => {
    if (view === 'mail') setSelectedId(null)
    updateUrlState({ view }, { push: true })
  }

  const openCreateDialog = () => {
    setEditingRecord(null)
    setRecordFormOpen(true)
  }

  const openEditDialog = (record: ApplicationRecord) => {
    setEditingRecord(record)
    setRecordFormOpen(true)
  }

  const selectedRecord = boardQuery.data.items.find((item) => item.id === selectedId) ?? null

  const handleStatusChange = (record: ApplicationRecord, group: BoardGroup) => {
    if (group === 'pending_review') {
      return
    }
    if (group === 'applied') {
      setConfirmAppliedRecord(record)
    } else {
      setStatusTarget({ record, target: group })
    }
  }

  const handleConfirmApplied = async () => {
    if (!confirmAppliedRecord) return
    await postEvent(confirmAppliedRecord.id, {
      stage: 'applied',
      event_date: todayDate(),
      source: 'user_confirmation',
    })
  }

  const afterWriteSuccess = (message: string) => {
    showToast(message, 'success')
    boardQuery.refetch()
    setDetailVersion((value) => value + 1)
  }

  const handleError = (message: string) => {
    showToast(message, 'error')
  }

  const handleDemoReset = async () => {
    setDemoResetting(true)
    try {
      await resetDemo()
      setSelectedId(null)
      setRecordFormOpen(false)
      setEditingRecord(null)
      setStatusTarget(null)
      setConfirmAppliedRecord(null)
      boardQuery.refetch()
      setDetailVersion((value) => value + 1)
      showToast('演示数据已重置', 'success')
    } catch (error) {
      handleError(error instanceof Error ? error.message : '重置演示数据失败')
    } finally {
      setDemoResetting(false)
    }
  }

  const content = effectiveView === 'mail' ? (
    <MailIngestionView
      onNotify={showToast}
      onEventCommitted={() => {
        boardQuery.refetch()
        setDetailVersion((value) => value + 1)
      }}
    />
  ) : effectiveView === 'board' ? (
      <BoardView
        items={boardQuery.data.items}
        loading={boardQuery.loading}
        error={boardQuery.error}
        counts={boardQuery.counts}
        stageGroup={urlState.stageGroup}
        selectedId={selectedId}
        onOpen={setSelectedId}
        onNewRecord={() => openCreateDialog()}
        onStageGroupChange={(value) => updateUrlState({ stageGroup: value })}
        onRetry={boardQuery.refetch}
        onStatusChange={handleStatusChange}
        onEmptyNewRecord={openCreateDialog}
      />
  ) : (
      <TableView
        items={boardQuery.data.items}
        total={boardQuery.data.total}
        page={urlState.page}
        pageSize={urlState.pageSize}
        loading={boardQuery.loading}
        error={boardQuery.error}
        sort={urlState.sort}
        selectedId={selectedId}
        onOpen={setSelectedId}
        onSortChange={(sort) => updateUrlState({ sort })}
        onPageChange={(page) => updateUrlState({ page })}
        onRetry={boardQuery.refetch}
        onEmptyNewRecord={openCreateDialog}
      />
  )

  return (
    <>
      <AppShell
        view={effectiveView}
        mailAvailable={mailAvailable}
        demoMode={isDemo}
        demoResetting={demoResetting}
        search={searchDraft}
        stageGroup={urlState.stageGroup}
        type={urlState.type}
        city={urlState.city}
        source={urlState.source}
        sort={urlState.sort}
        options={boardQuery.options}
        onViewChange={handleViewChange}
        onSearchChange={handleSearchChange}
        onSearchSubmit={handleSearchSubmit}
        onNewRecord={openCreateDialog}
        onStageGroupChange={(value) => updateUrlState({ stageGroup: value })}
        onTypeChange={(value) => updateUrlState({ type: value })}
        onCityChange={(value) => updateUrlState({ city: value })}
        onSourceChange={(value) => updateUrlState({ source: value })}
        onSortChange={(value) => updateUrlState({ sort: value })}
        onDemoReset={handleDemoReset}
      >
        {content}
      </AppShell>
      <DetailDrawer
        key={`detail-${selectedId ?? 'none'}-${detailVersion}`}
        recordId={selectedId}
        record={selectedRecord}
        onClose={() => setSelectedId(null)}
        onUpdateStatus={(record) => setStatusTarget({ record, target: 'free' })}
        onEdit={openEditDialog}
        onDeleted={(id) => {
          if (selectedId === id) setSelectedId(null)
          boardQuery.refetch()
          showToast('记录已删除', 'success')
        }}
        onError={handleError}
      />
      {recordFormOpen && (
        <RecordFormDialog
          mode={editingRecord ? 'edit' : 'create'}
          record={editingRecord}
          onDone={() => {
            setRecordFormOpen(false)
            afterWriteSuccess(editingRecord ? '已保存修改' : '记录已创建')
          }}
          onError={handleError}
          onClose={() => setRecordFormOpen(false)}
        />
      )}
      {statusTarget && (
        <StatusFormDialog
          target={statusTarget.target}
          record={statusTarget.record}
          onDone={() => {
            setStatusTarget(null)
            afterWriteSuccess('状态已更新')
          }}
          onError={handleError}
          onClose={() => setStatusTarget(null)}
        />
      )}
      {confirmAppliedRecord && (
        <ConfirmDialog
          title="确认已投递"
          message="确认已手动完成最终提交？确认后该记录将进入“已投递”。"
          confirmLabel="确认"
          onConfirm={handleConfirmApplied}
          onDone={() => {
            setConfirmAppliedRecord(null)
            afterWriteSuccess('已标记为已投递')
          }}
          onError={handleError}
          onClose={() => setConfirmAppliedRecord(null)}
        />
      )}
      <ToastViewport toasts={toasts} />
    </>
  )
}
