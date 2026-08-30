import FolderOpen from 'lucide-react/dist/esm/icons/folder-open'

export interface EmptyStateProps {
  onNewRecord?: () => void
}

export default function EmptyState({ onNewRecord }: EmptyStateProps) {
  return (
    <section className="statePanel" aria-label="空状态">
      <FolderOpen size={32} aria-hidden="true" className="stateIconMuted" />
      <p className="stateTitle">还没有申请记录</p>
      <p className="stateHint">用 Codex 将当前招聘表单准备到最终提交前，或手动新增记录。复核和正式提交始终由你本人完成。</p>
      {onNewRecord && (
        <button
          type="button"
          className="primaryButtonSmall"
          onClick={onNewRecord}
          data-testid="empty-new-record"
        >
          新增记录
        </button>
      )}
    </section>
  )
}
