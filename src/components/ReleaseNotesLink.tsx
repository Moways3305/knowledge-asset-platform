import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { ScrollText } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { fetchReleaseStatus, RELEASE_NOTES_CHANGED } from "../api/releaseNotes";

export default function ReleaseNotesLink() {
  const { authMe, status } = useAuth();
  const { pathname } = useLocation();
  const [unread, setUnread] = useState<{ user: string; count: number } | null>(null);
  const user = status === "authenticated" ? authMe?.userId : undefined;
  useEffect(() => {
    if (!user) return;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = () => {
      if (document.visibilityState === "hidden") return;
      controller?.abort();
      clearTimeout(timer);
      const request = new AbortController();
      controller = request;
      timer = setTimeout(() => request.abort(), 12000);
      void fetchReleaseStatus(request.signal)
        .then((value) => {
          if (!request.signal.aborted) setUnread({ user, count: value.unread_count });
        })
        .catch(() => {
          /* Retry the optional hint on focus. */
        });
    };
    refresh();
    window.addEventListener("focus", refresh);
    window.addEventListener(RELEASE_NOTES_CHANGED, refresh);
    return () => {
      controller?.abort();
      clearTimeout(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener(RELEASE_NOTES_CHANGED, refresh);
    };
  }, [user, pathname]);
  const hasUnread = unread?.user === user && (unread?.count ?? 0) > 0;
  return (
    <NavLink
      to="/release-notes"
      className="rail-foot-link"
      title="更新日志"
      aria-label={hasUnread ? "更新日志，有未读更新" : "更新日志"}
    >
      <ScrollText size={18} aria-hidden="true" />
      <span className="rail-foot-label">更新日志</span>
      {hasUnread && <span className="release-unread-dot" aria-hidden="true" />}
    </NavLink>
  );
}
