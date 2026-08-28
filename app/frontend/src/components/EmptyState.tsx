import FolderOpen from 'lucide-react/dist/esm/icons/folder-open'

export interface EmptyStateProps {
  onNewRecord?: () => void
}

export default function EmptyState({ onNewRecord }: EmptyStateProps) {
  return (
    <section className="statePanel" aria-label="空状态">
      <FolderOpen size={32} aria-hidden="true" className="stateIconMuted" />
      <p className="stateTitle">暂无投递记录</p>
      <p className="stateHint">创建第一条记录后，这里会展示你的投递进度。</p>
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
