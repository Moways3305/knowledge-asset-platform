import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import VirtualReviewList from "./VirtualReviewList";

afterEach(() => vi.restoreAllMocks());

it("mounts a bounded window of 598 rows and preserves edited drafts across scrolling", async () => {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(600);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1100);
  const items = Array.from({ length: 598 }, (_, index) => ({ id: `row-${index}` }));
  function Harness() {
    const ref = useRef<HTMLDivElement>(null);
    const [drafts, setDrafts] = useState<Record<string, string>>({});
    return (
      <div ref={ref} data-testid="scroll">
        <VirtualReviewList items={items} scrollRef={ref}>
          {(item) => (
            <input
              aria-label={item.id}
              value={drafts[item.id] ?? ""}
              onChange={(e) => setDrafts((current) => ({ ...current, [item.id]: e.target.value }))}
            />
          )}
        </VirtualReviewList>
      </div>
    );
  }
  render(<Harness />);
  const first = await screen.findByLabelText("row-0");
  expect(screen.getAllByRole("textbox").length).toBeLessThan(12);
  fireEvent.change(first, { target: { value: "人工标题" } });
  const scroll = screen.getByTestId("scroll");
  Object.defineProperty(scroll, "scrollTop", { configurable: true, writable: true, value: 20000 });
  fireEvent.scroll(scroll);
  await waitFor(() => expect(screen.queryByLabelText("row-0")).not.toBeInTheDocument());
  expect(screen.getAllByRole("textbox").length).toBeLessThan(12);
  scroll.scrollTop = 0;
  fireEvent.scroll(scroll);
  expect(await screen.findByLabelText("row-0")).toHaveValue("人工标题");
});
