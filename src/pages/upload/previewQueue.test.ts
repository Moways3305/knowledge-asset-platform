import { describe, expect, it, vi } from "vitest";
import { createPreviewQueue } from "./previewQueue";

describe("preview request budget", () => {
  it("caps concurrency and refills after failure", async () => {
    const queue = createPreviewQueue(2);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let active = 0;
    let peak = 0;
    const jobs = Array.from({ length: 100 }, (_, index) =>
      queue.run(async () => {
        active += 1;
        peak = Math.max(peak, active);
        await gate;
        active -= 1;
        if (index === 0) throw new Error("offline");
        return index;
      }),
    );
    const settled = Promise.allSettled(jobs);
    await Promise.resolve();
    expect(active).toBe(2);
    release();
    const results = await settled;
    expect(peak).toBe(2);
    expect(results.filter((item) => item.status === "rejected")).toHaveLength(1);
    expect(active).toBe(0);
  });

  it("clears waiting work without freeing an in-flight slot", async () => {
    const queue = createPreviewQueue(1);
    let release!: () => void;
    const first = queue.run(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    const stale = vi.fn(async () => 2);
    const cancelled = queue.run(stale);
    queue.clear();
    const fresh = vi.fn(async () => 3);
    const next = queue.run(fresh);
    await Promise.resolve();
    expect(await cancelled).toBeUndefined();
    expect(stale).not.toHaveBeenCalled();
    expect(fresh).not.toHaveBeenCalled();
    release();
    await first;
    expect(await next).toBe(3);
  });
});
