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
        description="了解每一次改进，让工作更从容。"
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
          <div className="release-glass-mark" aria-hidden="true">
            <Layers size={44} strokeWidth={1.2} />
          </div>
          <h3>持续打磨，每一步都有记录</h3>
          <p>由平台管理员发布，集中查看新增功能、体验优化与问题修复。</p>
          <div className="release-runtime">
            <span>当前服务版本</span>
            <strong>{version ? `v${version.replace(/^v/, "")}` : "暂未获取"}</strong>
          </div>
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
              <ReleaseNoteCard key={note.id} note={note} latest={page === 1 && index === 0} />
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
            <nav className="release-pagination" aria-label="日志分页">
              <button
                className="btn-secondary"
                disabled={page === 1}
                onClick={() => setPage(page - 1)}
              >
                上一页
              </button>
              <span>
                第 {page} / {Math.ceil(data.total / 10)} 页
              </span>
              <button
                className="btn-secondary"
                disabled={page * 10 >= data.total}
                onClick={() => setPage(page + 1)}
              >
                下一页
              </button>
            </nav>
          )}
        </section>
      </div>
    </ProductPage>
  );
}
