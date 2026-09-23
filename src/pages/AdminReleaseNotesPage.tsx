import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Eye, Plus, Send, Trash2, FilePenLine, ArrowUpRight } from "lucide-react";
import { ApiError } from "../api/http";
import {
  fetchReleaseNotes,
  saveReleaseNote,
  publishReleaseNote,
  invalidateReleaseNotes,
  type ReleaseDraft,
  type ReleaseNote,
  type ReleaseList,
  type ReleaseKind,
} from "../api/releaseNotes";
import { ProductPage, PageHeader } from "../components/ProductLayout";
import ReleaseNoteCard, { releaseDate, releaseKinds } from "../components/ReleaseNoteCard";
import TaskModal from "../components/TaskModal";
import "./ReleaseNotes.css";

const blank = (): ReleaseDraft => ({
  version: "",
  title: "",
  entries: [{ kind: "new", text: "" }],
  notify_users: true,
});
const draftOf = (note: ReleaseNote): ReleaseDraft => ({
  version: note.version,
  title: note.title,
  entries: note.entries.map((item) => ({ ...item })),
  notify_users: note.notify_users,
});

function ReleaseEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial: ReleaseNote | null;
  onClose: () => void;
  onSaved: (published: boolean) => void;
}) {
  const [note, setNote] = useState(initial);
  const [draft, setDraft] = useState<ReleaseDraft>(() => (initial ? draftOf(initial) : blank()));
  const [baseline, setBaseline] = useState(() =>
    JSON.stringify(initial ? draftOf(initial) : blank()),
  );
  const [preview, setPreview] = useState(Boolean(initial?.published_at));
  const [discard, setDiscard] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const locked = useRef(false);
  const readOnly = Boolean(note?.published_at);
  const deployed = Boolean(note?.source_commit && note?.deployed_at);
  const dirty = JSON.stringify(draft) !== baseline;
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const cleaned = (): ReleaseDraft => ({
    ...draft,
    version: draft.version.trim(),
    title: draft.title.trim(),
    entries: draft.entries
      .filter((item) => item.text.trim())
      .map((item) => ({ ...item, text: item.text.trim() })),
  });
  const validate = (publishing: boolean) => {
    const value = cleaned();
    if (!/^v?\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$/.test(value.version))
      return "请填写有效版本号，例如 v1.0.0。";
    if (!value.title) return "请填写更新标题。";
    if (publishing && !value.entries.length) return "请至少添加一条更新内容。";
    return "";
  };
  const close = () => {
    if (!busy) {
      if (dirty) setDiscard(true);
      else onClose();
    }
  };
  const persist = async (publishing: boolean) => {
    if (locked.current) return;
    const validation = validate(publishing);
    if (validation) {
      setError(validation);
      return;
    }
    locked.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      let saved = note;
      if (!saved || dirty) {
        saved = await saveReleaseNote(cleaned(), saved ?? undefined);
        setNote(saved);
        setDraft(draftOf(saved));
        setBaseline(JSON.stringify(draftOf(saved)));
      }
      if (publishing) {
        await publishReleaseNote(saved);
        invalidateReleaseNotes();
        onSaved(true);
        onClose();
      } else {
        setMessage("草稿已保存");
        onSaved(false);
      }
    } catch (err) {
      setError(
        err instanceof ApiError && [409, 422, 403].includes(err.status)
          ? err.message
          : "操作未完成，请检查网络后重试；可返回列表核对保存状态。",
      );
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  const showPreview = () => {
    const issue = validate(true);
    setError(issue);
    if (!issue) setPreview(true);
  };
  return (
    <>
      <TaskModal
        open={!discard}
        title={readOnly ? "已发布日志" : preview ? "发布预览" : "编辑版本日志"}
        size="large"
        panelClassName="release-editor-modal"
        portal
        description={
          readOnly ? "已发布内容保留为历史记录。" : "面向所有登录用户，清楚说明本次更新带来的变化。"
        }
        onClose={close}
        busy={busy}
        footer={
          <div className="release-editor-actions">
            {readOnly ? (
              <button className="btn-secondary" onClick={close}>
                关闭
              </button>
            ) : (
              <>
                <span className="release-muted">
                  {dirty ? "有未保存的修改" : note ? "草稿已保存" : "新建草稿"}
                </span>
                <button
                  className="btn-secondary"
                  disabled={busy}
                  onClick={() => void persist(false)}
                >
                  保存草稿
                </button>
                {preview ? (
                  <>
                    <button
                      className="btn-secondary"
                      disabled={busy}
                      onClick={() => setPreview(false)}
                    >
                      返回编辑
                    </button>
                    <button
                      className="btn-primary"
                      disabled={busy || !deployed}
                      onClick={() => void persist(true)}
                    >
                      <Send size={16} />
                      {busy ? "正在发布…" : "确认发布"}
                    </button>
                  </>
                ) : (
                  <button className="btn-primary" disabled={busy} onClick={showPreview}>
                    <Eye size={16} />
                    预览并发布
                  </button>
                )}
              </>
            )}
          </div>
        }
      >
        {error && (
          <p className="release-error" role="alert">
            {error}
          </p>
        )}
        {message && (
          <p role="status" className="release-success">
            {message}
          </p>
        )}
        {!readOnly && (
          <p className="release-publish-note">
            {deployed
              ? `已验证部署 · ${note?.source_commit?.slice(0, 12)} · ${releaseDate(note!.deployed_at!)}。请核对说明后发布。`
              : "待部署验证：可先保存和预览草稿，完成对应版本部署验证后才能发布公告。"}
          </p>
        )}
        {preview ? (
          <div className="release-preview">
            <ReleaseNoteCard note={readOnly && note ? note : cleaned()} />
            {!readOnly && (
              <p className="release-publish-note">
                发布后所有登录用户都可查看，
                {draft.notify_users ? "更新日志入口会显示未读提示。" : "本次不显示未读提示。"}
                发布不会部署系统更新。
              </p>
            )}
          </div>
        ) : (
          <fieldset className="release-form" disabled={busy}>
            <div className="release-form-top">
              <label>
                版本号
                <input
                  autoFocus
                  value={draft.version}
                  readOnly={deployed}
                  maxLength={40}
                  placeholder="例如 v1.0.0"
                  onChange={(event) => setDraft({ ...draft, version: event.target.value })}
                />
              </label>
              <label>
                更新标题
                <input
                  value={draft.title}
                  maxLength={120}
                  placeholder="用一句话概括本次更新"
                  onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                />
              </label>
            </div>
            <div className="release-field-heading">
              <h3>更新内容</h3>
              <span>按用户能感受到的变化逐条填写</span>
            </div>
            <div className="release-entry-fields">
              {draft.entries.map((entry, index) => (
                <div className="release-entry-field" key={index}>
                  <select
                    aria-label={`第 ${index + 1} 条类型`}
                    value={entry.kind}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        entries: draft.entries.map((item, i) =>
                          i === index ? { ...item, kind: event.target.value as ReleaseKind } : item,
                        ),
                      })
                    }
                  >
                    {Object.entries(releaseKinds).map(([key, value]) => (
                      <option key={key} value={key}>
                        {value}
                      </option>
                    ))}
                  </select>
                  <textarea
                    aria-label={`第 ${index + 1} 条内容`}
                    value={entry.text}
                    maxLength={500}
                    rows={2}
                    placeholder="说明功能变化或解决的问题"
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        entries: draft.entries.map((item, i) =>
                          i === index ? { ...item, text: event.target.value } : item,
                        ),
                      })
                    }
                  />
                  <button
                    className="release-remove"
                    type="button"
                    aria-label={`删除第 ${index + 1} 条`}
                    onClick={() =>
                      setDraft({ ...draft, entries: draft.entries.filter((_, i) => i !== index) })
                    }
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="release-text-button"
              disabled={draft.entries.length >= 50}
              onClick={() =>
                setDraft({ ...draft, entries: [...draft.entries, { kind: "improved", text: "" }] })
              }
            >
              <Plus size={16} />
              添加一条
            </button>
            <label className="release-notify">
              <input
                type="checkbox"
                checked={draft.notify_users}
                onChange={(event) => setDraft({ ...draft, notify_users: event.target.checked })}
              />
              发布后提醒用户<span>在更新日志入口显示未读提示</span>
            </label>
            <p className="release-publish-note">
              发布日志不会自动部署系统更新，请确认说明与实际上线内容一致。
            </p>
          </fieldset>
        )}
      </TaskModal>
      <TaskModal
        open={discard}
        title="放弃未保存的修改？"
        onClose={() => setDiscard(false)}
        portal
        size="small"
        footer={
          <>
            <button className="btn-secondary" onClick={() => setDiscard(false)}>
              继续编辑
            </button>
            <button className="btn-primary" onClick={onClose}>
              放弃修改
            </button>
          </>
        }
      >
        <p>已保存的草稿会保留，本次未保存的修改将丢失。</p>
      </TaskModal>
    </>
  );
}

export default function AdminReleaseNotesPage() {
  const [state, setState] = useState<"draft" | "published">("draft");
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<ReleaseList | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editor, setEditor] = useState<{ note: ReleaseNote | null } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError("");
    void fetchReleaseNotes(page, state, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("日志列表暂时无法加载，请重试。");
      });
    return () => controller.abort();
  }, [page, state, refresh]);
  return (
    <ProductPage className="release-page">
      <PageHeader
        className="release-hero"
        title="版本日志管理"
        description="部署验证后自动生成草稿，审核确认后再通知同事。"
        actions={
          <>
            <Link className="btn-secondary" to="/release-notes">
              用户视图
              <ArrowUpRight size={16} />
            </Link>
            <button
              className="btn-primary"
              onClick={() => {
                setNotice("");
                setEditor({ note: null });
              }}
            >
              <Plus size={16} />
              新建日志
            </button>
          </>
        }
      />
      {notice && (
        <p className="release-success" role="status">
          {notice}
        </p>
      )}
      <section className="release-management">
        <div className="release-tabs" role="tablist" aria-label="发布状态">
          {(["draft", "published"] as const).map((tab) => (
            <button
              key={tab}
              role="tab"
              aria-selected={state === tab}
              onClick={() => {
                setState(tab);
                setPage(1);
              }}
            >
              {tab === "draft" ? "草稿" : "已发布"}
            </button>
          ))}
        </div>
        {error ? (
          <div className="release-empty" role="alert">
            <p>{error}</p>
            <button className="btn-secondary" onClick={() => setRefresh((n) => n + 1)}>
              重试
            </button>
          </div>
        ) : !data ? (
          <p className="release-empty" role="status">
            正在加载日志…
          </p>
        ) : !data.items.length ? (
          <div className="release-empty">
            <FilePenLine size={32} />
            <h3>{state === "draft" ? "从一次值得记录的改进开始" : "还没有发布记录"}</h3>
            <p>
              {state === "draft"
                ? "完成版本化部署后，待审核草稿会自动出现在这里；也可提前编写。"
                : "草稿发布后，会保留在这里供你查阅。"}
            </p>
            {state === "draft" && (
              <button className="btn-primary" onClick={() => setEditor({ note: null })}>
                新建日志
              </button>
            )}
          </div>
        ) : (
          <div className="release-admin-list">
            {data.items.map((note) => (
              <button
                className="release-admin-row"
                key={note.id}
                onClick={() => setEditor({ note })}
              >
                <span className="release-version">{note.version}</span>
                <span className="release-row-content">
                  <strong>{note.title}</strong>
                  <small>
                    {note.entries.length} 条更新 · {note.notify_users ? "提醒用户" : "静默发布"}
                    {note.deployed_at ? " · 已验证部署" : " · 无部署验证记录"}
                  </small>
                </span>
                <span className="release-row-date">
                  {releaseDate(note.published_at ?? note.updated_at)}
                </span>
                <span className={`release-badge${state === "draft" ? " is-draft" : ""}`}>
                  {state === "draft" ? "编辑草稿" : "查看记录"}
                </span>
              </button>
            ))}
          </div>
        )}
        {data && data.total > 10 && (
          <nav className="release-pagination" aria-label="管理日志分页">
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
      {editor && (
        <ReleaseEditor
          initial={editor.note}
          onClose={() => {
            setEditor(null);
            setRefresh((n) => n + 1);
          }}
          onSaved={(published) => {
            setRefresh((n) => n + 1);
            if (published) {
              setState("published");
              setPage(1);
              setNotice("版本日志已发布，所有登录用户均可查看。");
            }
          }}
        />
      )}
    </ProductPage>
  );
}
