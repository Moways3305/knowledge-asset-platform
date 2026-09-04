import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import "./PagePagination.css";

function visiblePages(current: number, total: number): number[] {
  return [...new Set([1, current - 1, current, current + 1, total])].filter(
    (value) => value >= 1 && value <= total,
  );
}

interface PagePaginationProps {
  page: number;
  totalPages: number;
  hasNext?: boolean;
  disabled?: boolean;
  onPageChange: (page: number) => void;
  summary?: ReactNode;
  className?: string;
  ariaLabel: string;
}

/** Shared pagination: compact nearby pages plus an explicit jump to any page. */
export default function PagePagination({
  page,
  totalPages,
  hasNext = page < totalPages,
  disabled = false,
  onPageChange,
  summary,
  className,
  ariaLabel,
}: PagePaginationProps) {
  const [requestedPage, setRequestedPage] = useState(String(page));
  const safeTotalPages = Math.max(1, totalPages);

  useEffect(() => setRequestedPage(String(page)), [page]);

  const jump = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const target = Number.parseInt(requestedPage, 10);
    if (!Number.isInteger(target) || target < 1 || target > safeTotalPages || target === page)
      return;
    onPageChange(target);
  };

  const requested = Number.parseInt(requestedPage, 10);
  const canJump =
    Number.isInteger(requested) &&
    requested >= 1 &&
    requested <= safeTotalPages &&
    requested !== page;

  return (
    <div className={`page-pagination ${className ?? ""}`.trim()} aria-label={ariaLabel}>
      {summary && <span className="page-pagination-summary">{summary}</span>}
      <div className="page-pagination-actions">
        <div className="page-pagination-pages">
          <button
            type="button"
            aria-label="上一页"
            title="上一页"
            disabled={disabled || page <= 1}
            onClick={() => onPageChange(Math.max(1, page - 1))}
          >
            <ChevronLeft size={16} aria-hidden="true" />
          </button>
          {visiblePages(page, safeTotalPages).map((pageNumber) => (
            <button
              type="button"
              key={pageNumber}
              className={pageNumber === page ? "is-current" : ""}
              aria-label={`第 ${pageNumber} 页`}
              aria-current={pageNumber === page ? "page" : undefined}
              disabled={disabled}
              onClick={() => onPageChange(pageNumber)}
            >
              {pageNumber}
            </button>
          ))}
          <button
            type="button"
            aria-label="下一页"
            title="下一页"
            disabled={disabled || !hasNext}
            onClick={() => onPageChange(Math.min(safeTotalPages, page + 1))}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        </div>
        <form className="page-pagination-jump" onSubmit={jump}>
          <label>
            跳至
            <input
              aria-label="跳至指定页"
              inputMode="numeric"
              min={1}
              max={safeTotalPages}
              type="number"
              value={requestedPage}
              disabled={disabled}
              onChange={(event) => setRequestedPage(event.target.value)}
            />
            页
          </label>
          <button type="submit" disabled={disabled || !canJump}>
            跳转
          </button>
        </form>
      </div>
    </div>
  );
}
