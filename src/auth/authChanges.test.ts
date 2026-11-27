import { afterEach, expect, it, vi } from "vitest";
import { announceAuthChange, AUTH_CHANGE_KEY, subscribeAuthChanges } from "./authChanges";

afterEach(() => vi.restoreAllMocks());

it("publishes only an opaque revision and no identity or credentials", () => {
  const write = vi.spyOn(Storage.prototype, "setItem");
  announceAuthChange();
  expect(write).toHaveBeenCalledOnce();
  const [key, revision] = write.mock.calls[0];
  expect(key).toBe(AUTH_CHANGE_KEY);
  expect(revision).toMatch(/^[a-z0-9-]+$/);
  expect(revision.length).toBeLessThan(129);
});

it("continues safely when browser storage is unavailable", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("storage unavailable");
  });
  expect(() => announceAuthChange()).not.toThrow();
});

it("accepts only bounded revision markers and unsubscribes cleanly", () => {
  const changed = vi.fn();
  const unsubscribe = subscribeAuthChanges(changed);
  const send = (key: string, newValue: string | null) =>
    window.dispatchEvent(new StorageEvent("storage", { key, newValue }));
  send("unrelated", "anything");
  send(AUTH_CHANGE_KEY, null);
  send(AUTH_CHANGE_KEY, "x".repeat(129));
  send(AUTH_CHANGE_KEY, "valid");
  send(AUTH_CHANGE_KEY, "valid");
  expect(changed).toHaveBeenCalledOnce();
  unsubscribe();
  send(AUTH_CHANGE_KEY, "new");
  expect(changed).toHaveBeenCalledOnce();
});
