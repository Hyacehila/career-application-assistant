import { useMemo } from "react";
import type { KeyboardEvent } from "react";
import ArrowDown from "lucide-react/dist/esm/icons/arrow-down";
import ArrowUp from "lucide-react/dist/esm/icons/arrow-up";
import ChevronLeft from "lucide-react/dist/esm/icons/chevron-left";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right";
import type { ApplicationRecord } from "../api/client";
import type { BoardQueryError } from "../hooks/useBoardQuery";
import { cn } from "../lib/classNames";
import { formatDate } from "../lib/dates";
import { semanticColorOf, statusLabelOf } from "../lib/statuses";
import { useIsMobile } from "../lib/useIsMobile";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import LoadingState from "./LoadingState";
import styles from "./TableView.module.css";

export interface TableViewProps {
  items: ApplicationRecord[];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  error: BoardQueryError | null;
  sort: string;
  selectedId: number | null;
  onOpen: (id: number) => void;
  onSortChange: (sort: string) => void;
  onPageChange: (page: number) => void;
  onRetry: () => void;
  onEmptyNewRecord?: () => void;
}

const SORTABLE_COLUMNS: Array<{ key: string; label: string; field: string }> = [
  { key: "company", label: "公司", field: "company_name" },
  { key: "job", label: "岗位", field: "job_title" },
  { key: "updated", label: "更新时间", field: "updated_at" },
];

const FIXED_COLUMNS: string[] = ["类型", "地点", "当前阶段", "阶段日期", "投递日期", "来源"];

function stageDateOf(record: ApplicationRecord): string {
  const latestDate = record.latest_event?.event_date ? formatDate(record.latest_event.event_date) : "";
  if (latestDate) return latestDate;
  if (record.current_status === "applied") {
    const submitted = formatDate(record.submitted_at);
    if (submitted) return submitted;
  }
  const updated = formatDate(record.updated_at);
  if (updated) return updated;
  const filled = formatDate(record.filled_at);
  return filled;
}

function statusCell(record: ApplicationRecord) {
  return (
    <span className={styles.statusCell}>
      <span
        className={styles.statusDot}
        style={{ backgroundColor: semanticColorOf(record.current_status) }}
        aria-hidden="true"
      />
      {statusLabelOf(record.current_status)}
    </span>
  );
}

function MobileTableRows({
  items,
  selectedId,
  onOpen,
}: {
  items: ApplicationRecord[];
  selectedId: number | null;
  onOpen: (id: number) => void;
}) {
  const handleRowKey = (event: KeyboardEvent<HTMLElement>, id: number) => {
    if (event.key === "Enter") {
      event.preventDefault();
      onOpen(id);
    }
  };
  return (
    <div className={styles.mobileList} role="list" aria-label="投递记录列表">
      {items.map((record) => (
        <div
          key={record.id}
          role="listitem"
          tabIndex={0}
          data-testid={`table-row-${record.id}`}
          className={cn(styles.mobileRow, selectedId === record.id && styles.mobileRowSelected)}
          onClick={() => onOpen(record.id)}
          onKeyDown={(event) => handleRowKey(event, record.id)}
          aria-label={`${record.company_name} ${record.job_title}`}
        >
          <div className={styles.mobileRowTop}>
            <span className={styles.mobileRowCompany}>{record.company_name}</span>
            <span className={styles.mobileRowJob}>{record.job_title}</span>
          </div>
          <div className={styles.mobileRowBottom}>
            <span className={styles.statusCell}>
              <span
                className={styles.statusDot}
                style={{ backgroundColor: semanticColorOf(record.current_status) }}
                aria-hidden="true"
              />
              {statusLabelOf(record.current_status)}
            </span>
            <span className={cn(styles.mobileRowMeta, styles.muted)}>{stageDateOf(record) || "—"}</span>
            <span className={cn(styles.mobileRowMeta, styles.muted)}>
              更新 {formatDate(record.updated_at) || "—"}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function TableView({
  items,
  total,
  page,
  pageSize,
  loading,
  error,
  sort,
  selectedId,
  onOpen,
  onSortChange,
  onPageChange,
  onRetry,
  onEmptyNewRecord,
}: TableViewProps) {
  const isMobile = useIsMobile();
  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / Math.max(1, pageSize))), [total, pageSize])

  const handleHeadClick = (field: string) => {
    const base = field;
    if (sort === base) {
      onSortChange(`-${base}`);
    } else if (sort === `-${base}`) {
      onSortChange(base);
    } else {
      onSortChange(base);
    }
  };

  const handleRowKey = (event: KeyboardEvent<HTMLTableRowElement>, id: number) => {
    if (event.key === "Enter") {
      event.preventDefault();
      onOpen(id);
    }
  };

  if (loading) return <LoadingState />;
  if (error) return <ErrorState code={error.code} message={error.message} onRetry={onRetry} />;
  if (items.length === 0) return <EmptyState onNewRecord={onEmptyNewRecord} />;

  return (
    <div>
      {isMobile ? (
        <MobileTableRows items={items} selectedId={selectedId} onOpen={onOpen} />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                {SORTABLE_COLUMNS.slice(0, 2).map((column) => {
                  const asc = sort === column.field;
                  const desc = sort === `-${column.field}`;
                  const active = asc || desc;
                  return (
                    <th key={column.key} scope="col" className={cn(styles.tableHeadCell, styles.sortableHeadCell)} aria-sort={active ? (asc ? "ascending" : "descending") : "none"}>
                      <button type="button" onClick={() => handleHeadClick(column.field)} data-testid={`table-sort-${column.key}`}>
                        {column.label}
                        {asc && <ArrowUp size={14} aria-hidden="true" />}
                        {desc && <ArrowDown size={14} aria-hidden="true" />}
                      </button>
                    </th>
                  );
                })}
                {FIXED_COLUMNS.map((label) => (
                  <th key={label} scope="col" className={styles.tableHeadCell}>
                    {label}
                  </th>
                ))}
                <th scope="col" className={cn(styles.tableHeadCell, styles.sortableHeadCell)} aria-sort={sort === "updated_at" ? "ascending" : sort === "-updated_at" ? "descending" : "none"}>
                  <button type="button" onClick={() => handleHeadClick("updated_at")} data-testid="table-sort-updated">
                    {SORTABLE_COLUMNS[2].label}
                    {sort === "updated_at" && <ArrowUp size={14} aria-hidden="true" />}
                    {sort === "-updated_at" && <ArrowDown size={14} aria-hidden="true" />}
                  </button>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((record) => (
                <tr
                  key={record.id}
                  tabIndex={0}
                  data-testid={`table-row-${record.id}`}
                  className={cn(styles.row, selectedId === record.id && styles.rowSelected)}
                  onClick={() => onOpen(record.id)}
                  onKeyDown={(event) => handleRowKey(event, record.id)}
                  aria-label={`${record.company_name} ${record.job_title}`}
                >
                  <td className={cn(styles.rowCell, styles.rowCellCompany)}>{record.company_name}</td>
                  <td className={cn(styles.rowCell, styles.rowCellJob)}>{record.job_title}</td>
                  <td className={cn(styles.rowCell, record.application_type ? undefined : styles.muted)}>{record.application_type || "—"}</td>
                  <td className={cn(styles.rowCell, record.location ? undefined : styles.muted)}>{record.location || "—"}</td>
                  <td className={styles.rowCell}>{statusCell(record)}</td>
                  <td className={cn(styles.rowCell, styles.muted)} title="最近状态日期">{stageDateOf(record) || "—"}</td>
                  <td className={cn(styles.rowCell, styles.muted)}>{formatDate(record.submitted_at) || "—"}</td>
                  <td className={cn(styles.rowCell, record.source ? undefined : styles.muted)}>{record.source || "—"}</td>
                  <td className={cn(styles.rowCell, styles.muted)}>{formatDate(record.updated_at) || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className={styles.pagination}>
        <span className={styles.paginationInfo} data-testid="table-pagination-info">
          第 {page} / {totalPages} 页 · 共 {total} 条
        </span>
        <div className={styles.paginationControls}>
          <button
            type="button"
            className={styles.paginationButton}
            aria-label="上一页"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          <span className={styles.paginationPage}>{page}</span>
          <button
            type="button"
            className={styles.paginationButton}
            aria-label="下一页"
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
