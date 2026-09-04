import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type AnchorHTMLAttributes,
  type ReactNode,
} from "react";
import { useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { fetchKnowledgeDetail } from "../api/knowledge";
import { fetchProjectOverview } from "../api/project";
import { useAuth } from "../auth/AuthContext";
import { can, type Capabilities } from "../auth/permissions";

interface SafeHistoryEntry {
  pathname: string;
  search: string;
}

interface SafeNavigationValue {
  goBack: (options?: { fallback?: string }) => Promise<void>;
}

const STORAGE_KEY = "kap.safe-navigation.v1";
const MAX_ENTRIES = 20;
const SafeNavigationContext = createContext<SafeNavigationValue | null>(null);

const staticRoutes: Array<[RegExp, (capabilities: Capabilities) => boolean]> = [
  [/^\/$/, can.viewHome],
  [/^\/help$/, can.viewHelp],
  [/^\/knowledge$/, can.viewKnowledge],
  [/^\/my\/knowledge$/, can.viewMyKnowledge],
  [/^\/upload$/, can.viewUpload],
  [/^\/review$/, can.viewReview],
  [/^\/review\/completed$/, can.viewReview],
  [/^\/original-access$/, can.viewOriginalAccess],
  [/^\/admin\/ingest$/, can.viewIngestAdmin],
  [/^\/admin\/wecom-scan$/, can.viewWecomScan],
  [/^\/admin\/weknora-models$/, can.viewModels],
  [/^\/admin\/audit$/, can.viewAudit],
  [/^\/admin\/auth-security$/, can.viewAuthSecurity],
  [/^\/admin\/alert-settings$/, can.viewAlerts],
  [/^\/admin\/people$/, can.viewPeople],
  [/^\/admin\/company-kb$/, can.viewCompanyKnowledge],
  [/^\/admin\/permissions$/, can.viewPermissions],
];

function safeSearch(search: string): string | null {
  if (!search) return "";
  // Query parameters are page state, not a destination.  Dropping unknown
  // parameters here made a browser/app back action lose list filters, the
  // selected tab, and the current page.  The pathname is separately checked
  // against the internal route allow-list, so retaining a syntactically safe
  // query cannot turn this into an external redirect.
  if (
    !search.startsWith("?") ||
    Array.from(search).some((character) => character.charCodeAt(0) < 32)
  ) {
    return null;
  }
  return search;
}

function isSyntacticallyAllowed(entry: SafeHistoryEntry, capabilities: Capabilities): boolean {
  if (safeSearch(entry.search) === null) return false;
  const matched = staticRoutes.find(([pattern]) => pattern.test(entry.pathname));
  if (matched) return matched[1](capabilities);
  if (/^\/knowledge\/[^/]+$/.test(entry.pathname)) return can.viewKnowledge(capabilities);
  if (/^\/project\/[^/]+(?:\/knowledge|\/settings)?$/.test(entry.pathname)) {
    return can.viewProject(capabilities);
  }
  return false;
}

async function stillExists(entry: SafeHistoryEntry): Promise<boolean> {
  const knowledge = entry.pathname.match(/^\/knowledge\/([^/]+)$/);
  if (knowledge) {
    try {
      await fetchKnowledgeDetail(decodeURIComponent(knowledge[1]));
      return true;
    } catch {
      return false;
    }
  }
  const project = entry.pathname.match(/^\/project\/([^/]+)(?:\/knowledge|\/settings)?$/);
  if (project) {
    try {
      await fetchProjectOverview(decodeURIComponent(project[1]));
      return true;
    } catch {
      return false;
    }
  }
  return true;
}

function readHistory(): SafeHistoryEntry[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (entry): entry is SafeHistoryEntry =>
        typeof entry?.pathname === "string" &&
        entry.pathname.startsWith("/") &&
        !entry.pathname.startsWith("//") &&
        typeof entry?.search === "string",
    );
  } catch {
    return [];
  }
}

function writeHistory(entries: SafeHistoryEntry[]) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(entries.slice(-MAX_ENTRIES)));
}

export function SafeNavigationProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const { capabilities, status } = useAuth();
  const historyRef = useRef<SafeHistoryEntry[]>(readHistory());

  useEffect(() => {
    if (status !== "authenticated") return;
    const entry = {
      pathname: location.pathname,
      search: safeSearch(location.search) ?? "",
    };
    if (!isSyntacticallyAllowed(entry, capabilities)) return;
    const last = historyRef.current[historyRef.current.length - 1];
    if (last?.pathname === entry.pathname && last.search === entry.search) return;
    // A browser/client Back action must rewind our fallback stack as well.
    // Without this, a later in-app "返回" can jump to a page the user has
    // already left instead of the immediately preceding one.
    if (navigationType === "POP") {
      const existingIndex = historyRef.current
        .map((candidate) => `${candidate.pathname}${candidate.search}`)
        .lastIndexOf(`${entry.pathname}${entry.search}`);
      if (existingIndex >= 0) {
        historyRef.current = historyRef.current.slice(0, existingIndex + 1);
        writeHistory(historyRef.current);
        return;
      }
    }
    historyRef.current = [...historyRef.current, entry].slice(-MAX_ENTRIES);
    writeHistory(historyRef.current);
  }, [capabilities, location.pathname, location.search, navigationType, status]);

  const goBack = useCallback(
    async (options?: { fallback?: string }) => {
      const current = `${location.pathname}${location.search}`;
      const candidates = [...historyRef.current];
      while (candidates.length) {
        const candidate = candidates.pop()!;
        if (`${candidate.pathname}${candidate.search}` === current) continue;
        if (!isSyntacticallyAllowed(candidate, capabilities)) continue;
        if (!(await stillExists(candidate))) continue;
        historyRef.current = candidates;
        writeHistory(candidates);
        // Prefer the browser history entry when this visit happened inside KAP:
        // it restores native page state such as scroll position.  The safe stack
        // remains the source of truth for a direct link or a stale history item.
        if (typeof window !== "undefined" && Number(window.history.state?.idx) > 0) {
          navigate(-1);
        } else {
          navigate(`${candidate.pathname}${candidate.search}`, { replace: true });
        }
        return;
      }
      historyRef.current = [];
      writeHistory([]);
      const fallback = options?.fallback;
      if (fallback && isSafeInternalPath(fallback)) {
        navigate(fallback, { replace: true });
        return;
      }
      navigate("/", { replace: true });
    },
    [capabilities, location.pathname, location.search, navigate],
  );

  const value = useMemo(() => ({ goBack }), [goBack]);
  return <SafeNavigationContext.Provider value={value}>{children}</SafeNavigationContext.Provider>;
}

export function useSafeNavigation(): SafeNavigationValue {
  const value = useContext(SafeNavigationContext);
  if (!value) {
    return {
      goBack: async (options) => {
        window.location.assign(
          options?.fallback && isSafeInternalPath(options.fallback) ? options.fallback : "/",
        );
      },
    };
  }
  return value;
}

function isSafeInternalPath(value: string): boolean {
  return (
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !value.includes("\\") &&
    !Array.from(value).some((character) => character.charCodeAt(0) < 32)
  );
}

/**
 * A semantic in-app Back control.  Unlike a Link to a fixed route, it returns
 * to the page that led here and only uses `fallback` for direct/deep links.
 */
export function HistoryBackButton({
  fallback,
  children,
  onClick,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { fallback: string }) {
  const { goBack } = useSafeNavigation();
  return (
    <a
      {...props}
      href={fallback}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) {
          event.preventDefault();
          void goBack({ fallback });
        }
      }}
    >
      {children}
    </a>
  );
}
