import { useState, type ReactNode } from "react";
import ChevronDown from "lucide-react/dist/esm/icons/chevron-down";
import Plus from "lucide-react/dist/esm/icons/plus";
import SlidersHorizontal from "lucide-react/dist/esm/icons/sliders-horizontal";
import Info from "lucide-react/dist/esm/icons/info";
import Filters from "./Filters";
import { cn } from "../lib/classNames";
import { useIsMobile } from "../lib/useIsMobile";
import type { ListOptions } from "../api/client";
import type { ViewName } from "../hooks/useUrlState";
import styles from "./AppShell.module.css";

export interface AppShellProps {
  view: ViewName;
  mailAvailable: boolean;
  demoMode: boolean;
  demoResetting: boolean;
  search: string;
  stageGroup: string;
  type: string;
  city: string;
  source: string;
  sort: string;
  options: ListOptions;
  onViewChange: (view: ViewName) => void;
  onSearchChange: (value: string) => void;
  onSearchSubmit: () => void;
  onNewRecord: () => void;
  onStageGroupChange: (value: string) => void;
  onTypeChange: (value: string) => void;
  onCityChange: (value: string) => void;
  onSourceChange: (value: string) => void;
  onSortChange: (value: string) => void;
  onDemoReset: () => void;
  children: ReactNode;
}

const VIEW_ITEMS: Array<{ key: ViewName; label: string }> = [
  { key: "board", label: "看板" },
  { key: "table", label: "表格" },
  { key: "mail", label: "邮箱接入" },
];

export default function AppShell({
  view,
  mailAvailable,
  demoMode,
  demoResetting,
  search,
  stageGroup,
  type,
  city,
  source,
  sort,
  options,
  onViewChange,
  onSearchChange,
  onSearchSubmit,
  onNewRecord,
  onStageGroupChange,
  onTypeChange,
  onCityChange,
  onSourceChange,
  onSortChange,
  onDemoReset,
  children,
}: AppShellProps) {
  const isMobile = useIsMobile();
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const isMailView = view === "mail";
  const filterProps = {
    stageGroup,
    type,
    city,
    source,
    sort,
    options,
    onStageGroupChange,
    onTypeChange,
    onCityChange,
    onSourceChange,
    onSortChange,
  };
  return (
    <div className={cn(styles.shell, isMobile && styles.shellMobile)}>
      <header className={styles.header}>
        <div className={styles.topRow}>
          <div className={styles.topLeft} data-testid="shell-top-left">
            <span
              className={styles.productName}
              aria-label="求职投递助手 / Career Application Assistant"
            >
              <span>求职投递助手</span>
              <span className={styles.productNameEnglish}>/ Career Application Assistant</span>
            </span>
            <nav className={styles.viewSwitcher} aria-label="视图切换">
              {VIEW_ITEMS.filter((item) => item.key !== "mail" || mailAvailable).map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={cn(styles.viewButton, view === item.key && styles.viewButtonActive)}
                  aria-pressed={view === item.key}
                  onClick={() => onViewChange(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </nav>
            {!isMailView ? <form className={styles.searchForm} onSubmit={(event) => { event.preventDefault(); onSearchSubmit(); }}>
              <label className={styles.searchLabel} htmlFor="board-search">
                搜索
              </label>
              <input
                id="board-search"
                className={styles.searchInput}
                type="search"
                placeholder="搜索公司或岗位"
                value={search}
                onChange={(event) => onSearchChange(event.target.value)}
              />
            </form> : null}
          </div>
          {!isMailView ? <button type="button" className={styles.primaryButton} data-testid="new-record-button" onClick={onNewRecord}>
            <Plus size={16} aria-hidden="true" />
            <span>新增记录</span>
          </button> : null}
        </div>
        {!isMailView && (isMobile ? (
          <div className={styles.mobileFilterBar}>
            <button
              type="button"
              className={styles.mobileFilterToggle}
              data-testid="mobile-filter-toggle"
              aria-expanded={mobileFiltersOpen}
              aria-controls="mobile-filter-panel"
              onClick={() => setMobileFiltersOpen((value) => !value)}
            >
              <SlidersHorizontal size={16} aria-hidden="true" />
              <span>筛选</span>
              <ChevronDown
                size={16}
                aria-hidden="true"
                className={cn(styles.mobileFilterChevron, mobileFiltersOpen && styles.mobileFilterChevronOpen)}
              />
            </button>
            {mobileFiltersOpen && (
              <div id="mobile-filter-panel" className={styles.mobileFilterPanel} data-testid="mobile-filter-panel">
                <Filters {...filterProps} hideStageGroup />
              </div>
            )}
          </div>
        ) : (
          <div className={styles.filterRow}>
            <Filters {...filterProps} />
          </div>
        ))}
      </header>
      {demoMode ? (
        <aside className={styles.demoNotice} data-testid="demo-notice" aria-label="合成演示数据">
          <Info size={16} aria-hidden="true" className={styles.demoNoticeIcon} />
          <p>
            <strong>合成演示数据</strong>
            <span>所有公司、岗位和时间线均为虚构；操作只影响本次临时会话。</span>
          </p>
          <button
            type="button"
            className={styles.demoResetButton}
            data-testid="demo-reset"
            disabled={demoResetting}
            onClick={onDemoReset}
          >
            {demoResetting ? "正在重置…" : "重置演示"}
          </button>
        </aside>
      ) : null}
      <main className={styles.content} data-testid="shell-content">
        {children}
      </main>
    </div>
  );
}
