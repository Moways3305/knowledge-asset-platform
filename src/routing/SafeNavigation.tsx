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
import {
  isSafeInternalPath,
  readKnowledgeDetailSource,
  type KnowledgeDetailSourceState,
} from "./knowledgeDetailSource";

interface SafeHistoryEntry {
  pathname: string;
  search: string;
  hash?: string;
  state?: KnowledgeDetailSourceState;
}

interface SafeNavigationValue {
  goBack: (options?: { fallback?: string }) => Promise<void>;
}

const STORAGE_KEY = "kap.safe-navigation.v2";
const MAX_ENTRIES = 20;
const SafeNavigationContext = createContext<SafeNavigationValue | null>(null);

const staticRoutes: Array<[RegExp, (capabilities: Capabilities) => boolean]> = [
  [/^\/projects$/, can.viewProjectHub],
  [/^\/$/, can.viewHome],
  [/^\/help$/, can.viewHelp],
  [/^\/release-notes$/, can.viewReleaseNotes],
  [/^\/admin\/release-notes$/, can.manageReleaseNotes],
  [/^\/knowledge$/, can.viewKnowledge],
  [/^\/knowledge-maintenance$/, can.viewKnowledge],
  [/^\/agents(?:\/knowledge-maintenance)?$/, can.viewKnowledge],
  [/^\/ai-workspace(?:\/agents\/knowledge-maintenance)?\/?$/, can.viewKnowledge],
  [/^\/company-governance$/, can.viewCompanyKnowledge],
  [/^\/my\/knowledge$/, can.viewMyKnowledge],
  [/^\/my\/workbuddy$/, can.viewWorkbuddy],
  [/^\/upload$/, can.viewUpload],
  [/^\/review$/, can.viewReview],
  [/^\/review\/completed$/, can.viewReview],
  [/^\/original-access$/, can.viewOriginalAccess],
  [/^\/original-access\/grants$/, can.viewOriginalAccess],
  [/^\/admin\/ingest$/, can.viewIngestAdmin],
  [/^\/admin\/weknora-models$/, can.viewModels],
  [/^\/admin\/audit$/, can.viewAudit],
  [/^\/admin\/auth-security$/, can.viewAuthSecurity],
  [/^\/admin\/alert-settings$/, can.viewAlerts],
  [/^\/admin\/people$/, can.viewPeople],
  [/^\/admin\/company-kb$/, can.viewCompanyKnowledge],
  [/^\/admin\/naming-rules$/, can.viewNamingRules],
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
  if (!isSafeInternalPath(entry.pathname)) return false;
  if (safeSearch(entry.search) === null) return false;
  if (
    entry.hash &&
    (!entry.hash.startsWith("#") ||
      Array.from(entry.hash).some((character) => character.charCodeAt(0) < 32))
  )
    return false;
  const matched = staticRoutes.find(([pattern]) => pattern.test(entry.pathname));
  if (matched) return matched[1](capabilities);
  if (/^\/knowledge\/[^/]+$/.test(entry.pathname)) return can.viewKnowledge(capabilities);
  if (/^\/project\/[^/]+(?:\/knowledge|\/settings)?$/.test(entry.pathname)) {
    return can.viewProject(capabilities);
  }
  return false;
}

function historyPath(entry: SafeHistoryEntry): string {
  return `${entry.pathname}${entry.search}${entry.hash ?? ""}`;
}

function navigationSource(state: unknown): KnowledgeDetailSourceState | undefined {
  if (!state || typeof state !== "object") return undefined;
  const candidate = state as Partial<KnowledgeDetailSourceState>;
  if (!isSafeInternalPath(candidate.backTo) || !candidate.backLabel || !candidate.source) {
    return undefined;
  }
  const source = readKnowledgeDetailSource(state);
  // Persist only the checked return address/label/type, never arbitrary page
  // state such as draft contents or private API objects.
  return source.source === candidate.source ? source : undefined;
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

function readHistory(storageKey: string): SafeHistoryEntry[] {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(storageKey) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (entry): entry is SafeHistoryEntry =>
          typeof entry?.pathname === "string" &&
          entry.pathname.startsWith("/") &&
          !entry.pathname.startsWith("//") &&
          typeof entry?.search === "string" &&
          (entry.hash === undefined || typeof entry.hash === "string"),
      )
      .map((entry) => ({
        pathname: entry.pathname,
        search: entry.search,
        hash: entry.hash,
        state: navigationSource(entry.state),
      }));
  } catch {
    return [];
  }
}

function writeHistory(storageKey: string, entries: SafeHistoryEntry[]) {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(entries.slice(-MAX_ENTRIES)));
  } catch {
    // Navigation remains usable when browser storage is unavailable.
  }
}

export function SafeNavigationProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const { capabilities, status, authMe } = useAuth();
  const storageKey = `${STORAGE_KEY}:${authMe?.userId ?? "anonymous"}:${authMe?.activeCompanyRole ?? ""}`;
  const historyRef = useRef<SafeHistoryEntry[]>([]);
  const ownerRef = useRef("");
  const previousLocationRef = useRef<SafeHistoryEntry | null>(null);
  const currentPath = historyPath(location);
  const generation = useRef(0);
  const activeLocation = useRef(location.key);
  const mounted = useRef(true);
  if (ownerRef.current !== storageKey) {
    ownerRef.current = storageKey;
    historyRef.current = readHistory(storageKey);
    previousLocationRef.current = null;
    generation.current += 1;
  }
  if (activeLocation.current !== location.key) {
    activeLocation.current = location.key;
    generation.current += 1;
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
    };
  }, []);

  useEffect(() => {
    if (status !== "authenticated") return;
    const entry = {
      pathname: location.pathname,
      search: safeSearch(location.search) ?? "",
      hash: location.hash,
      state: navigationSource(location.state),
    };
    const previousLocation = previousLocationRef.current;
    previousLocationRef.current = entry;
    if (!isSyntacticallyAllowed(entry, capabilities)) return;
    const last = historyRef.current[historyRef.current.length - 1];
    if (last && historyPath(last) === historyPath(entry)) return;
    // Replacing a query (for example closing a deep-linked drawer) replaces
    // the current entry, rather than creating a Back destination that reopens it.
    // goBack already trims the stack, so only replace an entry that still
    // matches the route we just left.
    if (
      navigationType === "REPLACE" &&
      previousLocation &&
      last &&
      historyPath(last) === historyPath(previousLocation)
    ) {
      historyRef.current = [...historyRef.current.slice(0, -1), entry];
      writeHistory(storageKey, historyRef.current);
      return;
    }
    // A browser/client Back action must rewind our fallback stack as well.
    // Without this, a later in-app "返回" can jump to a page the user has
    // already left instead of the immediately preceding one.
    if (navigationType === "POP") {
      const existingIndex = historyRef.current.map(historyPath).lastIndexOf(historyPath(entry));
      if (existingIndex >= 0) {
        historyRef.current = historyRef.current.slice(0, existingIndex + 1);
        writeHistory(storageKey, historyRef.current);
        return;
      }
    }
    historyRef.current = [...historyRef.current, entry].slice(-MAX_ENTRIES);
    writeHistory(storageKey, historyRef.current);
  }, [
    capabilities,
    location.pathname,
    location.search,
    location.hash,
    location.state,
    navigationType,
    status,
    storageKey,
  ]);

  const goBack = useCallback(
    async (options?: { fallback?: string }) => {
      const current = currentPath;
      const request = ++generation.current;
      const candidates = [...historyRef.current];
      while (candidates.length) {
        const candidate = candidates.pop()!;
        if (historyPath(candidate) === current) continue;
        if (!isSyntacticallyAllowed(candidate, capabilities)) continue;
        const exists = await stillExists(candidate);
        if (!mounted.current || request !== generation.current) return;
        if (!exists) continue;
        historyRef.current = candidates;
        writeHistory(storageKey, candidates);
        // Browsers do not expose the pathname of the previous native history
        // entry. An index alone cannot prove that it still matches this validated
        // candidate after replaceState or a permission change, so never follow an
        // opaque native entry here.
        navigate(historyPath(candidate), { replace: true, state: candidate.state });
        return;
      }
      historyRef.current = [];
      writeHistory(storageKey, []);
      const fallback = options?.fallback;
      if (fallback && isSafeInternalPath(fallback)) {
        navigate(fallback, { replace: true });
        return;
      }
      navigate("/", { replace: true });
    },
    [capabilities, currentPath, navigate, storageKey],
  );

  const value = useMemo(() => ({ goBack }), [goBack]);
  return <SafeNavigationContext.Provider value={value}>{children}</SafeNavigationContext.Provider>;
}

export function useSafeNavigation(): SafeNavigationValue {
  const value = useContext(SafeNavigationContext);
  const navigate = useNavigate();
  if (!value) {
    return {
      goBack: async (options) => {
        navigate(
          options?.fallback && isSafeInternalPath(options.fallback) ? options.fallback : "/",
          { replace: true },
        );
      },
    };
  }
  return value;
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
        if (
          !event.defaultPrevented &&
          event.button === 0 &&
          !event.metaKey &&
          !event.ctrlKey &&
          !event.shiftKey &&
          !event.altKey &&
          (!props.target || props.target === "_self")
        ) {
          event.preventDefault();
          void goBack({ fallback });
        }
      }}
    >
      {children}
    </a>
  );
}
