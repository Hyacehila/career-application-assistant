import { APPLICATION_TYPES, type ListOptions } from "../api/client";
import { BOARD_GROUP_LABELS, type BoardGroup } from "../lib/statuses";
import styles from "./Filters.module.css";

export interface FiltersProps {
  type: string;
  city: string;
  source: string;
  sort: string;
  stageGroup: string;
  options: ListOptions;
  onTypeChange: (value: string) => void;
  onCityChange: (value: string) => void;
  onSourceChange: (value: string) => void;
  onSortChange: (value: string) => void;
  onStageGroupChange: (value: string) => void;
  hideStageGroup?: boolean;
}

const SORT_LATEST = "updated_at";
const SORT_EARLIEST = "-updated_at";

function FilterField({
  id,
  label,
  value,
  options,
  allowAll,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: string[];
  allowAll: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className={styles.field} htmlFor={id}>
      <span className={styles.fieldLabel}>{label}</span>
      <select
        id={id}
        className={styles.select}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {allowAll && <option value="">全部</option>}
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function Filters({
  type,
  city,
  source,
  sort,
  stageGroup,
  options,
  onTypeChange,
  onCityChange,
  onSourceChange,
  onSortChange,
  onStageGroupChange,
  hideStageGroup,
}: FiltersProps) {
  const stageGroupOptions = Object.keys(BOARD_GROUP_LABELS) as BoardGroup[];
  const typeOptions = [
    ...APPLICATION_TYPES,
    ...options.types.filter((item) => !(APPLICATION_TYPES as readonly string[]).includes(item)),
  ];
  return (
    <div className={styles.filters} role="group" aria-label="记录筛选">
      {!hideStageGroup && (
        <label className={styles.field} htmlFor="filter-stage-group">
          <span className={styles.fieldLabel}>状态分组</span>
          <select
            id="filter-stage-group"
            className={styles.select}
            value={stageGroup}
            onChange={(event) => onStageGroupChange(event.target.value)}
          >
            <option value="">全部</option>
            {stageGroupOptions.map((group) => (
              <option key={group} value={group}>
                {BOARD_GROUP_LABELS[group]}
              </option>
            ))}
          </select>
        </label>
      )}
      <FilterField
        id="filter-type"
        label="投递类型"
        value={type}
        options={typeOptions}
        allowAll
        onChange={onTypeChange}
      />
      <FilterField id="filter-city" label="城市" value={city} options={options.cities} allowAll onChange={onCityChange} />
      <FilterField id="filter-source" label="来源" value={source} options={options.sources} allowAll onChange={onSourceChange} />
      <label className={styles.field} htmlFor="filter-sort">
        <span className={styles.fieldLabel}>更新时间</span>
        <select
          id="filter-sort"
          className={styles.select}
          value={sort}
          onChange={(event) => onSortChange(event.target.value)}
        >
          <option value={SORT_LATEST}>最新优先</option>
          <option value={SORT_EARLIEST}>最早优先</option>
        </select>
      </label>
    </div>
  );
}
