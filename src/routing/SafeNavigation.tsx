import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchKnowledgeDetail } from "../api/knowledge";
import { fetchProjectOverview } from "../api/project";
import { useAuth } from "../auth/AuthContext";
import { can, type Capabilities } from "../auth/permissions";

interface SafeHistoryEntry {
  pathname: string;
  search: string;
}

interface SafeNavigationValue {
  goBack: () => Promise<void>;
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

function safeSearch(pathname: string, search: string): string | null {
  if (!search) return "";
  const params = new URLSearchParams(search);
  if (pathname === "/knowledge") {
    if ([...params.keys()].some((key) => key !== "scope")) return null;
    const scope = params.get("scope");
    return scope === null || ["company", "personal", "project"].includes(scope)
      ? params.toString()
        ? `?${params.toString()}`
        : ""
      : null;
  }
  if (pathname === "/upload") {
    if ([...params.keys()].some((key) => key !== "source")) return null;
    const source = params.get("source");
    return source === null || ["local", "wecom"].includes(source)
      ? params.toString()
        ? `?${params.toString()}`
        : ""
      : null;
  }
  return null;
}

function isSyntacticallyAllowed(entry: SafeHistoryEntry, capabilities: Capabilities): boolean {
  if (safeSearch(entry.pathname, entry.search) === null) return false;
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
  const { capabilities, status } = useAuth();
  const historyRef = useRef<SafeHistoryEntry[]>(readHistory());

  useEffect(() => {
    if (status !== "authenticated") return;
    const entry = {
      pathname: location.pathname,
      search: safeSearch(location.pathname, location.search) ?? "",
    };
    if (!isSyntacticallyAllowed(entry, capabilities)) return;
    const last = historyRef.current[historyRef.current.length - 1];
    if (last?.pathname === entry.pathname && last.search === entry.search) return;
    historyRef.current = [...historyRef.current, entry].slice(-MAX_ENTRIES);
    writeHistory(historyRef.current);
  }, [capabilities, location.pathname, location.search, status]);

  const goBack = useCallback(async () => {
    const current = `${location.pathname}${location.search}`;
    const candidates = [...historyRef.current];
    while (candidates.length) {
      const candidate = candidates.pop()!;
      if (`${candidate.pathname}${candidate.search}` === current) continue;
      if (!isSyntacticallyAllowed(candidate, capabilities)) continue;
      if (!(await stillExists(candidate))) continue;
      historyRef.current = candidates;
      writeHistory(candidates);
      navigate(`${candidate.pathname}${candidate.search}`, { replace: true });
      return;
    }
    historyRef.current = [];
    writeHistory([]);
    navigate("/", { replace: true });
  }, [capabilities, location.pathname, location.search, navigate]);

  const value = useMemo(() => ({ goBack }), [goBack]);
  return <SafeNavigationContext.Provider value={value}>{children}</SafeNavigationContext.Provider>;
}

export function useSafeNavigation(): SafeNavigationValue {
  const value = useContext(SafeNavigationContext);
  if (!value) {
    return {
      goBack: async () => {
        window.location.assign("/");
      },
    };
  }
  return value;
}
