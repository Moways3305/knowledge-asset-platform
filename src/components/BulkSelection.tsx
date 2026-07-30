import { useEffect, useRef, type ReactNode } from "react";
import "./BulkSelection.css";

export function SelectionCheckbox({
  checked,
  indeterminate = false,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  indeterminate?: boolean;
  disabled?: boolean;
  label: string;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={onChange}
      type="checkbox"
    />
  );
}

export function BulkSelectionRail({
  selectedCount,
  pageSelectedCount,
  matchingCount,
  allMatchingSelected,
  matchingPending = false,
  busy,
  onSelectAllMatching,
  onClear,
  children,
}: {
  selectedCount: number;
  pageSelectedCount: number;
  matchingCount: number;
  allMatchingSelected: boolean;
  matchingPending?: boolean;
  busy?: boolean;
  onSelectAllMatching?: () => void;
  onClear: () => void;
  children: ReactNode;
}) {
  if (selectedCount === 0) return null;
  return (
    <div className="bulk-selection-rail" role="region" aria-label="批量操作">
      <div className="bulk-selection-copy" aria-live="polite">
        <strong>
          {allMatchingSelected
            ? `已选择全部符合当前筛选条件的 ${selectedCount} 项`
            : `已选择本页 ${pageSelectedCount} 项`}
        </strong>
        {matchingPending && <span>正在核对筛选结果中的可操作项…</span>}
        {!allMatchingSelected && matchingCount > pageSelectedCount && onSelectAllMatching && (
          <button disabled={busy} onClick={onSelectAllMatching} type="button">
            选择全部符合当前筛选条件的 {matchingCount} 项
          </button>
        )}
        <button disabled={busy} onClick={onClear} type="button">
          清除选择
        </button>
      </div>
      <div className="bulk-selection-actions">{children}</div>
    </div>
  );
}
