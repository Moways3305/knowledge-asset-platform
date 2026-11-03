import PagePagination from "../components/PagePagination";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Layers, Settings2 } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import {
  fetchReleaseNotes,
  fetchReleaseStatus,
  readReleaseNotes,
  invalidateReleaseNotes,
  type ReleaseList,
} from "../api/releaseNotes";
import ReleaseNoteCard from "../components/ReleaseNoteCard";
import { ProductPage, PageHeader } from "../components/ProductLayout";
import "./ReleaseNotes.css";

export default function ReleaseNotesPage() {
  const { authMe, capabilities } = useAuth();
  const [page, setPage] = useState(1);
  const [attempt, setAttempt] = useState(0);
  const [data, setData] = useState<ReleaseList | null>(null);
  const [version, setVersion] = useState("");
  const [error, setError] = useState("");
  const [readError, setReadError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    setReadError(false);
    setVersion("");
    void fetchReleaseStatus(controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setVersion(result.running_version);
      })
      .catch(() => {});
    void fetchReleaseNotes(page, undefined, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("更新日志暂时无法加载，请重试。");
      });
    return () => controller.abort();
  }, [page, attempt, authMe?.userId]);
  useEffect(() => {
    const ids = data?.items.filter((note) => note.is_unread).map((note) => note.id) ?? [];
    if (!ids.length) return;
    let active = true;
    void readReleaseNotes(ids)
      .then(() => {
        if (active) {
          setData((current) =>
            current && current === data
              ? { ...current, items: current.items.map((note) => ({ ...note, is_unread: false })) }
              : current,
          );
          invalidateReleaseNotes();
        }
      })
      .catch(() => {
        if (active) setReadError(true);
      });
    return () => {
      active = false;
    };
  }, [data]);
  return (
    <ProductPage className="release-page">
      <PageHeader
        className="release-hero"
        title="更新日志"
        description="查看已发布的功能更新与问题修复。"
        actions={
          capabilities.isAdmin && (
            <Link className="btn-secondary" to="/admin/release-notes">
              <Settings2 size={16} />
              管理日志
            </Link>
          )
        }
      />
      <div className="release-reading-layout">
        <aside className="release-context">
          <div className="release-runtime">
            <span>当前服务版本</span>
            <strong>{version ? `v${version.replace(/^v/, "")}` : "暂未获取"}</strong>
          </div>
          {data && data.items.length > 0 && (
            <nav className="release-version-index" aria-label="本页版本">
              <h3>本页版本</h3>
              {data.items.map((note) => (
                <a key={note.id} href={`#release-${note.id}`}>
                  <strong>{note.version}</strong>
                  <span>{note.title}</span>
                </a>
              ))}
            </nav>
          )}
        </aside>
        <section className="release-timeline" aria-label="版本更新记录" aria-busy={!data && !error}>
          {error ? (
            <div className="release-empty" role="alert">
              <p>{error}</p>
              <button className="btn-secondary" onClick={() => setAttempt((n) => n + 1)}>
                重试
              </button>
            </div>
          ) : !data ? (
            <p role="status">正在加载更新日志…</p>
          ) : !data.items.length ? (
            <div className="release-empty">
              <Layers size={30} />
              <h3>还没有发布更新日志</h3>
              <p>管理员发布后，你可以在这里查看平台的改进。</p>
            </div>
          ) : (
            data.items.map((note, index) => (
              <div
                key={note.id}
                id={`release-${note.id}`}
                tabIndex={-1}
                className="release-history-entry"
              >
                <ReleaseNoteCard note={note} latest={page === 1 && index === 0} />
              </div>
            ))
          )}
          {readError && (
            <p role="status" className="release-muted">
              已读状态未同步。
              <button className="release-text-button" onClick={() => setAttempt((n) => n + 1)}>
                重试同步
              </button>
            </p>
          )}
          {data && data.total > 10 && (
            <PagePagination
              ariaLabel="日志分页"
              page={page}
              totalPages={Math.ceil(data.total / 10)}
              onPageChange={setPage}
              summary={`共 ${data.total} 条`}
            />
          )}
        </section>
      </div>
    </ProductPage>
  );
}
