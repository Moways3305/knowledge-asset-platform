import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";

/** Drafts live in the controller, never in the mounted virtual card. */
export default function VirtualReviewList<T extends { id: string }>({
  items,
  scrollRef,
  resetKey,
  children,
}: {
  items: T[];
  scrollRef: RefObject<HTMLDivElement>;
  resetKey?: string;
  children: (item: T) => ReactNode;
}) {
  const listRef = useRef<HTMLDivElement>(null);
  const [margin, setMargin] = useState(0);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const enabled = items.length > 30;
  const getItemKey = useCallback((index: number) => items[index].id, [items]);
  const focusedIndex = items.findIndex((item) => item.id === focusedId);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => listRef.current?.parentElement ?? scrollRef.current,
    getItemKey,
    estimateSize: () => 430,
    overscan: 2,
    gap: 12,
    scrollMargin: margin,
    enabled,
    rangeExtractor: (range) => {
      const indexes = defaultRangeExtractor(range);
      // Do not unmount the active editor when the user scrolls with the mouse.
      return focusedIndex < 0
        ? indexes
        : [...new Set([...indexes, focusedIndex])].sort((a, b) => a - b);
    },
  });
  useLayoutEffect(() => {
    const list = listRef.current;
    if (list) setMargin(list.offsetTop);
  }, [items, enabled]);
  // Filtering/deletion must not leave the viewport below the shortened list.
  useLayoutEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [items.length, scrollRef, resetKey]);
  if (!enabled)
    return (
      <>
        {items.map((item) => (
          <div key={item.id}>{children(item)}</div>
        ))}
      </>
    );
  return (
    <div ref={listRef} style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
      {virtualizer.getVirtualItems().map((virtualRow) => {
        const item = items[virtualRow.index];
        return (
          <div
            key={item.id}
            data-index={virtualRow.index}
            ref={virtualizer.measureElement}
            onFocusCapture={() => setFocusedId(item.id)}
            onBlurCapture={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null))
                setFocusedId(null);
            }}
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              transform: `translateY(${virtualRow.start - margin}px)`,
            }}
          >
            {children(item)}
          </div>
        );
      })}
    </div>
  );
}
