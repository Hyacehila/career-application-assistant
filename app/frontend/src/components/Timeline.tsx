import type { ApplicationEvent } from '../api/client'
import { formatDate, formatTime } from '../lib/dates'
import { statusLabelOf } from '../lib/statuses'
import { cn } from '../lib/classNames'
import styles from './DetailDrawer.module.css'

export interface TimelineProps {
  events: ApplicationEvent[]
  currentEventId: number | null
}

function metaLineOf(event: ApplicationEvent): string {
  const parts: string[] = []
  const scheduledDate = formatDate(event.scheduled_date)
  if (scheduledDate) {
    const scheduledTime = formatTime(event.scheduled_time)
    parts.push(`计划 ${scheduledDate}${scheduledTime ? ` ${scheduledTime}` : ''}`)
  }
  const deadlineDate = formatDate(event.deadline_date)
  if (deadlineDate) {
    const deadlineTime = formatTime(event.deadline_time)
    parts.push(`截止 ${deadlineDate}${deadlineTime ? ` ${deadlineTime}` : ''}`)
  }
  const completedDate = formatDate(event.completed_date)
  if (completedDate) parts.push(`完成 ${completedDate}`)
  if (event.mode) {
    const modeLabels: Record<string, string> = { online: '线上', offline: '线下', phone: '电话' }
    parts.push(modeLabels[event.mode] ?? event.mode)
  }
  if (event.location) parts.push(event.location)
  return parts.join(' · ')
}

export default function Timeline({ events, currentEventId }: TimelineProps) {
  if (events.length === 0) {
    return <p className={styles.timelineNote} style={{ color: 'var(--color-text-secondary)' }}>暂无事件</p>
  }
  return (
    <ol className={styles.timeline}>
      {events.map((event, index) => {
        const isCurrent = event.id === currentEventId
        const meta = metaLineOf(event)
        return (
          <li
            key={event.id}
            className={cn(styles.timelineItem, isCurrent && styles.timelineItemCurrent)}
            data-testid={isCurrent ? 'timeline-current' : undefined}
          >
            <span className={cn(styles.timelineDot, isCurrent && styles.timelineDotCurrent)} aria-hidden="true" />
            <div className={styles.timelineBody}>
              <div className={styles.timelineHead}>
                <span className={styles.timelineStage}>{statusLabelOf(event.stage)}</span>
                <span className={styles.timelineDate}>{formatDate(event.event_date)}</span>
              </div>
              {meta && <span className={styles.timelineMeta}>{meta}</span>}
              {event.note && <span className={styles.timelineNote}>{event.note}</span>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
