import { describe, expect, it } from "vitest";

import {
  buildUploadTransportBatches,
  LOCAL_UPLOAD_MAX_BYTES,
  TRANSPORT_BATCH_MAX_BYTES,
} from "./uploadIntake";

function item(name: string, size: number) {
  return { file: new File([new Uint8Array(size)], name, { type: "text/plain" }) };
}

describe("buildUploadTransportBatches", () => {
  it("splits 196 files into sequential requests of at most ten files", () => {
    const batches = buildUploadTransportBatches(
      Array.from({ length: 196 }, (_, index) => item(`${index}.txt`, 1)),
    );
    expect(batches.map((batch) => batch.length)).toEqual([
      ...Array.from({ length: 19 }, () => 10),
      6,
    ]);
  });

  it("cuts on raw byte size without exceeding 20 MiB", () => {
    const batches = buildUploadTransportBatches([
      item("a.txt", 12 * 1024 * 1024),
      item("b.txt", 9 * 1024 * 1024),
      item("c.txt", 1),
    ]);
    expect(batches.map((batch) => batch.map((entry) => entry.file.name))).toEqual([
      ["a.txt"],
      ["b.txt", "c.txt"],
    ]);
    expect(batches.flat().every((entry) => entry.file.size <= LOCAL_UPLOAD_MAX_BYTES)).toBe(true);
  });

  it("allows a 20-25 MiB file only as its own request", () => {
    const large = item("large.pdf", TRANSPORT_BATCH_MAX_BYTES + 1024);
    const batches = buildUploadTransportBatches([item("a.txt", 1), large, item("b.txt", 1)]);
    expect(batches.map((batch) => batch.map((entry) => entry.file.name))).toEqual([
      ["a.txt"],
      ["large.pdf"],
      ["b.txt"],
    ]);
  });
});
