// Cross-tab invalidation contains an opaque revision only. Identity and credentials
// stay in the authoritative /auth/me response and httpOnly cookies.
const CHANNEL = "kap.auth.changed";
export const AUTH_CHANGE_KEY = "kap.auth.revision";
let serial = 0;

export function announceAuthChange(): void {
  const revision = `${Date.now().toString(36)}-${++serial}-${globalThis.crypto?.randomUUID?.() ?? "changed"}`;
  try {
    localStorage.setItem(AUTH_CHANGE_KEY, revision);
  } catch {
    // BroadcastChannel also works when persistent browser storage is blocked.
  }
  try {
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(CHANNEL);
      channel.postMessage(revision);
      channel.close();
    }
  } catch {
    // Focus/visibility revalidation remains available without either transport.
  }
}

export function subscribeAuthChanges(changed: () => void): () => void {
  const seen = new Set<string>();
  const receive = (revision: unknown) => {
    if (typeof revision !== "string" || !revision || revision.length > 128 || seen.has(revision))
      return;
    seen.add(revision);
    if (seen.size > 32) seen.delete(seen.values().next().value!);
    changed();
  };
  const storage = (event: StorageEvent) => {
    if (event.key === AUTH_CHANGE_KEY) receive(event.newValue);
  };
  window.addEventListener("storage", storage);
  let channel: BroadcastChannel | undefined;
  try {
    if (typeof BroadcastChannel !== "undefined") {
      channel = new BroadcastChannel(CHANNEL);
      channel.onmessage = (event: MessageEvent<unknown>) => receive(event.data);
    }
  } catch {
    // The storage event path does not depend on BroadcastChannel availability.
  }
  return () => {
    window.removeEventListener("storage", storage);
    channel?.close();
  };
}
