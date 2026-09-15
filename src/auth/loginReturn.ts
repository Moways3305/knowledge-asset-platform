// Only a short-lived, same-origin path is retained across the OAuth round trip.
// No credentials, OAuth codes or tokens belong in browser storage.
const KEY = "kap.login-return";
export function rememberLoginReturn(path: string) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ path, at: Date.now() }));
  } catch {
    /* Login still works when storage is disabled. */
  }
}
export function consumeLoginReturn(): string | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
    if (!raw) return null;
    const { path, at } = JSON.parse(raw);
    if (
      typeof path !== "string" ||
      typeof at !== "number" ||
      Date.now() - at > 600_000 ||
      at > Date.now()
    )
      return null;
    const url = new URL(path, window.location.origin);
    if (
      !path.startsWith("/") ||
      path.startsWith("//") ||
      path.includes("\\") ||
      url.origin !== window.location.origin ||
      url.pathname === "/login"
    )
      return null;
    return url.pathname + url.search + url.hash;
  } catch {
    return null;
  }
}
