import { useDraggable } from '@dnd-kit/core'
import type { KeyboardEvent } from 'react'
import type { ApplicationRecord } from '../api/client'
import { cn } from '../lib/classNames'
import { boardGroupOf } from '../lib/statuses'
import { stagePresentationOf } from '../lib/stagePresentation'
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
  const presentation = stagePresentationOf(record)
  const cardLabel = `${record.company_name} ${record.job_title} ${presentation.text}`
  const cardTitle = `${record.company_name} · ${record.job_title} · ${presentation.text}`

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Enter') {
      if (!isDragging) {
        event.preventDefault()
        onClick()
      }
      return
    }

    listeners?.onKeyDown?.(event)
  }

  return (
    <article
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      style={style}
      data-testid={`board-card-${record.id}`}
      className={cn(styles.card, selected && styles.cardSelected, isDragging && styles.cardDragging, dragging && draggingClassName)}
      aria-label={cardLabel}
      title={cardTitle}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
    >
      <div className={styles.cardTop}>
        <span className={styles.company}>{record.company_name}</span>
        <span className={styles.job}>{record.job_title}</span>
      </div>
      <span className={styles.cardStatus} data-testid={`board-card-status-${record.id}`}>
        <span
          className={styles.cardStatusDot}
          style={{ backgroundColor: presentation.color }}
          aria-hidden="true"
        />
        <span>{presentation.text}</span>
      </span>
    </article>
  )
}
