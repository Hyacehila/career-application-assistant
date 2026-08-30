import { useMemo, useState } from "react";
import {
  DndContext,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  pointerWithin,
  rectIntersection,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import Plus from "lucide-react/dist/esm/icons/plus";
import type { ApplicationRecord } from "../api/client";
import type { BoardQueryError } from "../hooks/useBoardQuery";
import { cn } from "../lib/classNames";
import { BOARD_GROUPS, BOARD_GROUP_LABELS, boardGroupOf, type BoardGroup } from "../lib/statuses";
import { useIsMobile } from "../lib/useIsMobile";
import BoardCard from "./BoardCard";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import LoadingState from "./LoadingState";
import styles from "./BoardView.module.css";

const boardCollisionDetection: CollisionDetection = (args) => (
  args.pointerCoordinates ? pointerWithin(args) : rectIntersection(args)
);

export interface BoardViewProps {
  items: ApplicationRecord[];
  loading: boolean;
  error: BoardQueryError | null;
  counts: Record<BoardGroup, number>;
  stageGroup: string;
  selectedId: number | null;
  onOpen: (id: number) => void;
  onNewRecord: (group: BoardGroup) => void;
  onRetry: () => void;
  onStatusChange: (record: ApplicationRecord, group: BoardGroup) => void;
  onStageGroupChange?: (value: string) => void;
  onEmptyNewRecord?: () => void;
}

function StageTrack() {
  return (
    <div className={styles.stageTrack} aria-hidden="true">
      <div className={styles.stageTrackLine} />
      {BOARD_GROUPS.map((group) => (
        <div key={group} className={styles.stageTrackNode} />
      ))}
    </div>
  );
}

function BoardColumn({
  group,
  records,
  count,
  isOver,
  selectedId,
  activeDragId,
  onOpen,
  onNewRecord,
}: {
  group: BoardGroup;
  records: ApplicationRecord[];
  count: number;
  isOver: boolean;
  selectedId: number | null;
  activeDragId: number | null;
  onOpen: (id: number) => void;
  onNewRecord: (group: BoardGroup) => void;
}) {
  const { setNodeRef, isOver: dropActive } = useDroppable({ id: group });
  const over = isOver || dropActive;
  return (
    <section className={cn(styles.column, over && styles.columnActive)} aria-label={BOARD_GROUP_LABELS[group]}>
      <div className={styles.columnHead}>
        <span className={styles.columnTitle}>{BOARD_GROUP_LABELS[group]}</span>
        <span className={styles.columnCount}>{count}</span>
      </div>
      <div ref={setNodeRef} data-testid={`droppable-${group}`} className={styles.columnCards}>
        {records.length === 0 && <div className={styles.columnEmpty}>暂无记录</div>}
        {records.map((record) => (
          <BoardCard
            key={record.id}
            record={record}
            selected={selectedId === record.id}
            dragging={activeDragId === record.id}
            draggingClassName={over ? styles.cardDropOver : undefined}
            onClick={() => onOpen(record.id)}
          />
        ))}
      </div>
      <button
        type="button"
        className={styles.columnAdd}
        data-testid={`board-add-${group}`}
        onClick={() => onNewRecord(group)}
      >
        <Plus size={14} aria-hidden="true" />
        <span>添加记录</span>
      </button>
    </section>
  );
}

const STAGE_CHIP_ORDER: BoardGroup[] = ["pending_review", "applied", "assessment", "interview", "ended"];

function isBoardGroup(value: string): value is BoardGroup {
  return (BOARD_GROUPS as readonly string[]).includes(value);
}

function MobileStageSelector({
  stageGroup,
  counts,
  onChange,
}: {
  stageGroup: BoardGroup;
  counts: Record<BoardGroup, number>;
  onChange: (value: string) => void;
}) {
  return (
    <div className={styles.stageChips} role="tablist" aria-label="阶段筛选" data-testid="stage-chip-row">
      {STAGE_CHIP_ORDER.map((chip) => {
        const active = chip === stageGroup;
        const count = counts[chip];
        return (
          <button
            key={chip}
            type="button"
            role="tab"
            aria-selected={active}
            data-testid={`stage-chip-${chip}`}
            className={cn(styles.stageChip, active && styles.stageChipActive)}
            onClick={() => onChange(chip)}
          >
            <span className={styles.stageChipLabel}>{BOARD_GROUP_LABELS[chip]}</span>
            <span className={styles.stageChipCount}>{count}</span>
          </button>
        );
      })}
    </div>
  );
}

function MobileBoardList({
  group,
  records,
  count,
  selectedId,
  onOpen,
  onNewRecord,
}: {
  group: BoardGroup;
  records: ApplicationRecord[];
  count: number;
  selectedId: number | null;
  onOpen: (id: number) => void;
  onNewRecord: (group: BoardGroup) => void;
}) {
  return (
    <section className={styles.mobileColumn} aria-label={BOARD_GROUP_LABELS[group]}>
      <div className={styles.columnHead}>
        <span className={styles.columnTitle}>{BOARD_GROUP_LABELS[group]}</span>
        <span className={styles.columnCount}>{count}</span>
      </div>
      <div className={styles.columnCards}>
        {records.length === 0 && <div className={styles.columnEmpty}>暂无记录</div>}
        {records.map((record) => (
          <BoardCard
            key={record.id}
            record={record}
            selected={selectedId === record.id}
            dragging={false}
            onClick={() => onOpen(record.id)}
          />
        ))}
      </div>
      <button
        type="button"
        className={styles.columnAdd}
        data-testid={`board-add-${group}`}
        onClick={() => onNewRecord(group)}
      >
        <Plus size={14} aria-hidden="true" />
        <span>添加记录</span>
      </button>
    </section>
  );
}

export default function BoardView({
  items,
  loading,
  error,
  counts,
  stageGroup,
  selectedId,
  onOpen,
  onNewRecord,
  onRetry,
  onStatusChange,
  onStageGroupChange,
  onEmptyNewRecord,
}: BoardViewProps) {
  const isMobile = useIsMobile();
  const [activeDragId, setActiveDragId] = useState<number | null>(null);
  const [overGroup, setOverGroup] = useState<BoardGroup | null>(null);

  const mouseSensor = useSensor(MouseSensor, { activationConstraint: { distance: 6 } });
  const touchSensor = useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 8 } });
  const keyboardSensor = useSensor(KeyboardSensor);
  const sensors = useSensors(mouseSensor, touchSensor, keyboardSensor);

  const grouped = useMemo(() => {
    const byGroup: Record<BoardGroup, ApplicationRecord[]> = {
      pending_review: [],
      applied: [],
      assessment: [],
      interview: [],
      ended: [],
    };
    for (const record of items) {
      const group = boardGroupOf(record.current_status);
      byGroup[group].push(record);
    }
    for (const group of BOARD_GROUPS) {
      byGroup[group].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    }
    return byGroup;
  }, [items]);

  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragId(Number(event.active.id));
  };

  const handleDragOver = (event: DragOverEvent) => {
    const over = event.over;
    if (over && typeof over.id === "string" && (BOARD_GROUPS as readonly string[]).includes(over.id)) {
      setOverGroup(over.id as BoardGroup);
    }
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDragId(null);
    const overGroupId = event.over?.id;
    setOverGroup(null);
    if (typeof overGroupId !== "string") return;
    const record = items.find((item) => String(item.id) === String(event.active.id));
    if (!record) return;
    const targetGroup = BOARD_GROUPS.find((group) => group === overGroupId);
    if (!targetGroup) return;
    if (boardGroupOf(record.current_status) === targetGroup) return;
    onStatusChange(record, targetGroup);
  };

  if (loading) return <LoadingState />;
  if (error) return <ErrorState code={error.code} message={error.message} onRetry={onRetry} />;
  if (items.length === 0) return <EmptyState onNewRecord={onEmptyNewRecord} />;

  if (isMobile) {
    // 窄屏：五个固定阶段 chip + 当前阶段单列。未指定分组时默认显示待确认投递。
    const mobileGroup: BoardGroup = isBoardGroup(stageGroup) ? stageGroup : "pending_review";
    return (
      <div className={cn(styles.boardContainer, styles.boardMobile)}>
        <MobileStageSelector
          stageGroup={mobileGroup}
          counts={counts}
          onChange={(value) => onStageGroupChange?.(value)}
        />
        <MobileBoardList
          group={mobileGroup}
          records={grouped[mobileGroup]}
          count={counts[mobileGroup]}
          selectedId={selectedId}
          onOpen={onOpen}
          onNewRecord={onNewRecord}
        />
      </div>
    );
  }

  return (
    <div className={styles.boardContainer}>
      <div className={styles.boardScroll}>
        <StageTrack />
        <DndContext
          sensors={sensors}
          collisionDetection={boardCollisionDetection}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDragEnd={handleDragEnd}
          onDragCancel={() => {
            setActiveDragId(null);
            setOverGroup(null);
          }}
        >
          <div className={styles.board}>
            {BOARD_GROUPS.map((group) => (
              <BoardColumn
                key={group}
                group={group}
                records={grouped[group]}
                count={counts[group]}
                isOver={overGroup === group}
                selectedId={selectedId}
                activeDragId={activeDragId}
                onOpen={onOpen}
                onNewRecord={onNewRecord}
              />
            ))}
          </div>
        </DndContext>
      </div>
    </div>
  );
}
