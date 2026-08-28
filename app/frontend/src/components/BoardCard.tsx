import { useDraggable } from '@dnd-kit/core'
import { BriefcaseBusiness, Clock3, MapPin, Tag } from 'lucide-react'
import type { KeyboardEvent } from 'react'
import type { ApplicationRecord } from '../api/client'
import { cn } from '../lib/classNames'
import { formatDateTime, formatDate } from '../lib/dates'
import { boardGroupOf, semanticColorOf, statusLabelOf } from '../lib/statuses'
import styles from './BoardView.module.css'

export interface BoardCardProps {
  record: ApplicationRecord
  selected: boolean
  dragging: boolean
  draggingClassName?: string
  onClick: () => void
}

export default function BoardCard({
  record,
  selected,
  dragging,
  draggingClassName,
  onClick,
}: BoardCardProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: String(record.id),
    data: { boardGroup: boardGroupOf(record.current_status) },
  })
  const style = transform
    ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`, zIndex: 5 }
    : undefined
  const accent = semanticColorOf(record.current_status)
  const updated = formatDateTime(record.updated_at)
  const latest = record.latest_event ?? null
  let highlightText: string | undefined
  if (record.current_status === 'assessment') {
    const scheduled = latest?.scheduled_date ? formatDate(latest.scheduled_date) : undefined
    const deadline = latest?.deadline_date ? formatDate(latest.deadline_date) : undefined
    if (scheduled && deadline) {
      highlightText = `计划 ${scheduled} / 截止 ${deadline}`
    } else if (scheduled) {
      highlightText = `计划 ${scheduled}`
    } else if (deadline) {
      highlightText = `截止 ${deadline}`
    } else {
      const fallback = formatDate(record.next_action_date)
      if (fallback) highlightText = `计划/截止 ${fallback}`
    }
  } else if (record.current_status.startsWith('interview_')) {
    const scheduled = latest?.scheduled_date ? formatDate(latest.scheduled_date) : undefined
    const fallback = formatDate(record.next_action_date)
    const date = scheduled ?? fallback
    highlightText = date
      ? `${statusLabelOf(record.current_status)} · ${date}`
      : statusLabelOf(record.current_status)
  } else if (
    record.current_status === 'offer' ||
    record.current_status === 'rejected' ||
    record.current_status === 'withdrawn'
  ) {
    highlightText = statusLabelOf(record.current_status)
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      onClick()
    }
  }

  return (
    <article
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      style={style}
      data-testid={`board-card-${record.id}`}
      className={cn(styles.card, selected && styles.cardSelected, isDragging && styles.cardDragging, dragging && draggingClassName)}
      aria-label={`${record.company_name} ${record.job_title}`}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      <div className={styles.cardTop}>
        <span className={styles.fieldLabel}>公司</span>
        <span className={styles.company}>{record.company_name}</span>
        <span className={styles.fieldLabel}>岗位</span>
        <span className={styles.job}>{record.job_title}</span>
      </div>
      {highlightText && (
        <div className={styles.highlight} style={{ color: accent }} data-testid={`board-card-highlight-${record.id}`}>
          {highlightText}
        </div>
      )}
      {(record.location || record.application_type || record.source || updated) && (
        <div className={styles.secondary}>
          {record.location && <span className={styles.metaItem}><MapPin size={13} aria-hidden="true" />{record.location}</span>}
          {record.application_type && <span className={styles.metaItem}><BriefcaseBusiness size={13} aria-hidden="true" />{record.application_type}</span>}
          {record.source && <span className={styles.metaItem}><Tag size={13} aria-hidden="true" />{record.source}</span>}
          {updated && <span className={cn(styles.metaItem, styles.updated)}><Clock3 size={13} aria-hidden="true" />更新 {updated}</span>}
        </div>
      )}
    </article>
  )
}
