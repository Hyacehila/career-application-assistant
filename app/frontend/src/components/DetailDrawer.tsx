import { useEffect, useRef, useState } from "react";
import MoreHorizontal from "lucide-react/dist/esm/icons/more-horizontal";
import Pencil from "lucide-react/dist/esm/icons/pencil";
import Trash2 from "lucide-react/dist/esm/icons/trash-2";
import X from "lucide-react/dist/esm/icons/x";
import { deleteApplication, type ApplicationRecord, type ApplicationEvent } from "../api/client";
import { useApplicationDetail } from "../hooks/useApplicationDetail";
import { useReducedMotion } from "../lib/useReducedMotion";
import { useIsMobile } from "../lib/useIsMobile";
import { cn } from "../lib/classNames";
import { formatDate } from "../lib/dates";
import { semanticColorOf, statusLabelOf } from "../lib/statuses";
import ErrorState from "./ErrorState";
import Timeline from "./Timeline";
import styles from "./DetailDrawer.module.css";

export interface DetailDrawerProps {
  recordId: number | null;
  record: ApplicationRecord | null;
  onClose: () => void;
  onUpdateStatus: (record: ApplicationRecord) => void;
  onEdit: (record: ApplicationRecord) => void;
  onDeleted: (id: number) => void;
  onError: (message: string) => void;
}

const CLOSING_ANIMATION_MS = 210;
const MOBILE_TIMELINE_LIMIT = 3;

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metaRow}>
      <span className={styles.metaKey}>{label}</span>
      <span className={styles.metaValue} title={value}>
        {value}
      </span>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className={styles.skeleton} aria-hidden="true">
      <div className={cn(styles.skeletonBar, styles.skeletonWide)} />
      <div className={cn(styles.skeletonBar, styles.skeletonNarrow)} />
      <div className={cn(styles.skeletonBar, styles.skeletonWide)} />
      <div className={cn(styles.skeletonBar, styles.skeletonNarrow)} />
    </div>
  );
}

export default function DetailDrawer({
  recordId,
  record,
  onClose,
  onUpdateStatus,
  onEdit,
  onDeleted,
  onError,
}: DetailDrawerProps) {
  const reduced = useReducedMotion();
  const isMobile = useIsMobile();
  const [closing, setClosing] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const bodyRef = useRef<HTMLElement | null>(null);
  const detail = useApplicationDetail(recordId);

  const open = recordId !== null && record !== null;

  const requestClose = () => {
    if (closing) return;
    setClosing(true);
    if (reduced) onClose();
  };

  useEffect(() => {
    if (!open) {
      setClosing(false);
      setMoreOpen(false);
      setConfirmDelete(false);
      setDeleting(false);
      setTimelineExpanded(false);
      return undefined;
    }
    bodyRef.current?.focus();
    return undefined;
  }, [open]);

  useEffect(() => {
    if (!closing) return undefined;
    const timer = window.setTimeout(onClose, reduced ? 0 : CLOSING_ANIMATION_MS);
    return () => window.clearTimeout(timer);
  }, [closing, reduced, onClose]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        requestClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const handleDelete = async () => {
    if (!record || deleting) return;
    setDeleting(true);
    try {
      await deleteApplication(record.id);
      onDeleted(record.id);
    } catch (error) {
      const message = error instanceof Error && error.message ? error.message : "删除失败，请稍后重试";
      onError(message);
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const events: ApplicationEvent[] = detail.data?.events ?? [];
  const currentEvent = events.length > 0 && events[0].stage === record.current_status ? events[0] : null;
  const accent = semanticColorOf(record.current_status);
  const stageDate = currentEvent ? formatDate(currentEvent.event_date) : "";
  const drawerStyle = reduced ? ({ transition: "none" } as const) : undefined;
  const visibleEvents =
    isMobile && !timelineExpanded && events.length > MOBILE_TIMELINE_LIMIT
      ? events.slice(0, MOBILE_TIMELINE_LIMIT)
      : events;

  return (
    <div className={styles.drawerWrap} data-testid="detail-drawer">
      <div
        className={cn(styles.backdrop, closing && styles.backdropEnd)}
        data-testid="detail-drawer-backdrop"
        onClick={requestClose}
      />
      <aside
        className={cn(
          styles.drawer,
          isMobile && styles.drawerBottom,
          closing && (isMobile ? styles.drawerBottomClosing : styles.drawerClosing),
        )}
        data-testid={isMobile ? "drawer-bottom" : "drawer-side"}
        style={drawerStyle}
        role="dialog"
        aria-modal="true"
        aria-label={`投递详情 ${record.company_name} ${record.job_title}`}
        ref={bodyRef}
        tabIndex={-1}
      >
        {isMobile && <div className={styles.sheetGrabber} aria-hidden="true" />}
        <div className={styles.drawerHead}>
          <div className={styles.drawerTitleGroup}>
            <span className={styles.drawerCompany}>{record.company_name}</span>
            <span className={styles.drawerJob}>{record.job_title}</span>
            <span className={styles.drawerRecordId}>记录 #{record.id}</span>
          </div>
          <button type="button" aria-label="关闭详情" onClick={requestClose} className="overlayCardClose">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className={styles.drawerBody}>
          {(record.department || record.job_code || record.application_type || record.location || record.source || record.job_url) && (
            <div className={styles.drawerMeta}>
              {record.department && <MetaRow label="部门" value={record.department} />}
              {record.job_code && <MetaRow label="岗位编号" value={record.job_code} />}
              {record.application_type && <MetaRow label="投递类型" value={record.application_type} />}
              {record.location && <MetaRow label="地点" value={record.location} />}
              {record.source && <MetaRow label="来源" value={record.source} />}
              {record.job_url && <MetaRow label="岗位网址" value={record.job_url} />}
            </div>
          )}

          <section aria-label="当前进度">
            <h3 className={styles.sectionLabel}>当前进度</h3>
            <div className={styles.progressPanel}>
              <div className={styles.progressHead}>
                <span className={styles.progressStatus} style={{ color: accent }} data-testid="drawer-current-status">
                  <span className={styles.progressDot} style={{ backgroundColor: accent }} aria-hidden="true" />
                  {statusLabelOf(record.current_status)}
                </span>
                {stageDate && (
                  <span className={styles.progressDate} data-testid="drawer-stage-date">
                    {stageDate}
                  </span>
                )}
              </div>
            </div>
          </section>

          <section aria-label="进度时间线">
            <h3 className={styles.sectionLabel}>进度时间线</h3>
            {detail.loading && !detail.data ? (
              <LoadingSkeleton />
            ) : detail.error && !detail.data ? (
              <ErrorState code={detail.error.code} message={detail.error.message} onRetry={detail.refetch} />
            ) : (
              <Timeline events={visibleEvents} currentEventId={currentEvent?.id ?? null} />
            )}
          </section>

          {(record.next_action || record.next_action_date || record.notes) && (
            <section aria-label="下一步">
              <h3 className={styles.sectionLabel}>下一步</h3>
              <div className={styles.nextActionPanel} data-testid="drawer-next-action">
                {record.next_action && <span className={styles.nextActionValue}>{record.next_action}</span>}
                {record.next_action_date && (
                  <span className={styles.nextActionLabel}>计划日期 {formatDate(record.next_action_date)}</span>
                )}
                {record.notes && <span className={styles.notesValue}>备注：{record.notes}</span>}
              </div>
            </section>
          )}
        </div>
        <div className={styles.drawerFoot}>
          {!isMobile && confirmDelete ? (
            <div className={styles.moreMenu} data-testid="drawer-delete-confirm">
              <span className={styles.moreMenuItem} style={{ color: "var(--color-text-secondary)" }}>
                确认软删除这条记录？
              </span>
              <div style={{ display: "flex", gap: 8, padding: "0 12px 12px" }}>
                <button type="button" className="secondaryButton" onClick={() => setConfirmDelete(false)} disabled={deleting}>
                  取消
                </button>
                <button type="button" className="dangerButton" onClick={handleDelete} disabled={deleting}>
                  {deleting ? "删除中…" : "确认删除"}
                </button>
              </div>
            </div>
          ) : !isMobile && moreOpen ? (
            <div className={styles.moreMenu} role="menu" aria-label="更多操作" data-testid="drawer-more-menu">
              <button type="button" className={styles.moreMenuItem} role="menuitem" onClick={() => onEdit(record)}>
                <Pencil size={16} aria-hidden="true" />
                <span>编辑岗位信息</span>
              </button>
              <button
                type="button"
                className={cn(styles.moreMenuItem, styles.moreMenuItemDanger)}
                role="menuitem"
                data-testid="drawer-delete-button"
                onClick={() => setConfirmDelete(true)}
              >
                <Trash2 size={16} aria-hidden="true" />
                <span>软删除</span>
              </button>
            </div>
          ) : null}
          <div className={styles.drawerActions}>
            <button type="button" className="flowButton" onClick={() => onUpdateStatus(record)}>
              更新状态
            </button>
            {isMobile ? (
              <button
                type="button"
                className="secondaryButton"
                data-testid="drawer-expand-timeline"
                aria-expanded={timelineExpanded}
                onClick={() => setTimelineExpanded((value) => !value)}
              >
                {timelineExpanded ? "收起时间线" : "查看详情"}
              </button>
            ) : (
              <button
                type="button"
                className="secondaryButton"
                aria-expanded={moreOpen}
                onClick={() => {
                  setConfirmDelete(false);
                  setMoreOpen((value) => !value);
                }}
              >
                <MoreHorizontal size={16} aria-hidden="true" />
                <span>更多操作</span>
              </button>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
