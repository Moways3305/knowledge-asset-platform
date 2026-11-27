import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, Copy, Download, FileText, Maximize2, Minimize2, Save, X } from "lucide-react";
import {
  getWorkspaceDetail,
  saveWorkspaceArtifact,
  type WorkspaceArtifact,
} from "../../api/aiWorkspace";
import { ApiError } from "../../api/http";
import { MarkdownView } from "../knowledge/OnlyOfficePreview";
import { workspaceError } from "./useWorkspaceData";

export interface ArtifactDraft {
  content: string;
  title: string;
  baseContent: string;
  baseTitle: string;
  revision: number;
}
export type PreviewTab = "document" | "edit" | "changes";

/** Linear comparison keeps very long drafts usable without a quadratic diff. */
export function draftDifference(before: string, after: string) {
  const oldLines = before.split("\n");
  const newLines = after.split("\n");
  let start = 0;
  while (
    start < oldLines.length &&
    start < newLines.length &&
    oldLines[start] === newLines[start]
  ) {
    start += 1;
  }
  let oldEnd = oldLines.length;
  let newEnd = newLines.length;
  while (oldEnd > start && newEnd > start && oldLines[oldEnd - 1] === newLines[newEnd - 1]) {
    oldEnd -= 1;
    newEnd -= 1;
  }
  return {
    start,
    removed: oldLines.slice(start, oldEnd).join("\n"),
    added: newLines.slice(start, newEnd).join("\n"),
  };
}

interface Props {
  sessionId: string;
  artifact: WorkspaceArtifact;
  draft?: ArtifactDraft;
  updateDraft: (id: string, update: (current: ArtifactDraft | undefined) => ArtifactDraft) => void;
  tab: PreviewTab;
  setTab: (tab: PreviewTab) => void;
  open: boolean;
  full: boolean;
  setFull: (full: boolean) => void;
  onClose: () => void;
  onSaved: () => void;
  savedScrollTop?: number;
  onScrollPosition?: (top: number) => void;
}

export default function ArtifactPanel({
  sessionId,
  artifact,
  draft,
  updateDraft,
  tab,
  setTab,
  open,
  full,
  setFull,
  onClose,
  onSaved,
  savedScrollTop = 0,
  onScrollPosition,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [discardConfirm, setDiscardConfirm] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const previewScroll = useRef<HTMLDivElement>(null);
  const scrollPosition = useRef(savedScrollTop);
  scrollPosition.current = savedScrollTop;
  useLayoutEffect(() => {
    if (previewScroll.current && open) previewScroll.current.scrollTop = scrollPosition.current;
  }, [artifact.id, open, tab]);
  const current: ArtifactDraft = draft ?? {
    title: artifact.title,
    content: artifact.content,
    baseContent: artifact.content,
    baseTitle: artifact.title,
    revision: artifact.revision,
  };
  const dirty = current.content !== current.baseContent || current.title !== current.baseTitle;
  const changed = draftDifference(current.baseContent, current.content);
  useEffect(() => {
    if (
      !draft ||
      draft.revision >= artifact.revision ||
      ((draft.content !== draft.baseContent || draft.title !== draft.baseTitle) &&
        (draft.content !== artifact.content || draft.title !== artifact.title))
    )
      return;
    updateDraft(artifact.id, () => ({
      title: artifact.title,
      content: artifact.content,
      baseContent: artifact.content,
      baseTitle: artifact.title,
      revision: artifact.revision,
    }));
  }, [artifact, draft, updateDraft]);

  function edit(update: Partial<ArtifactDraft>) {
    updateDraft(artifact.id, (previous) => ({ ...(previous ?? current), ...update }));
    setNotice("");
  }
  async function save() {
    if (busy || !dirty || !current.title.trim()) return;
    setBusy(true);
    setError("");
    const submitted = current;
    try {
      const saved = await saveWorkspaceArtifact(sessionId, artifact.id, {
        title: submitted.title.trim(),
        content: submitted.content,
        expected_revision: submitted.revision,
      });
      if (!mounted.current) return;
      updateDraft(artifact.id, (latest) => ({
        ...(latest ?? submitted),
        content: !latest || latest.content === submitted.content ? saved.content : latest.content,
        title: !latest || latest.title === submitted.title ? saved.title : latest.title,
        baseContent: saved.content,
        baseTitle: saved.title,
        revision: saved.revision,
      }));
      setNotice("已保存到当前会话");
      onSaved();
    } catch (cause) {
      if (!mounted.current) return;
      if (cause instanceof ApiError && cause.status === 409) {
        setConflict(true);
        onSaved();
      }
      setError(
        cause instanceof ApiError && cause.status === 409
          ? "文档已有更新。你的修改仍保留，可先复制或下载草稿，再载入最新版本进行合并。"
          : workspaceError(cause),
      );
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function reloadLatest() {
    setBusy(true);
    try {
      const snapshot = await getWorkspaceDetail(sessionId);
      if (!mounted.current) return;
      const latest = snapshot.artifacts.find((item) => item.id === artifact.id);
      if (!latest) {
        setError("当前已无法访问这份文档。");
        onSaved();
        return;
      }
      updateDraft(artifact.id, () => ({
        title: latest.title,
        content: latest.content,
        baseContent: latest.content,
        baseTitle: latest.title,
        revision: latest.revision,
      }));
      setError("");
      setConflict(false);
      setDiscardConfirm(false);
      setNotice("已载入最新版本");
      onSaved();
    } catch (cause) {
      if (mounted.current) setError(workspaceError(cause));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(current.content);
      setNotice("已复制文档");
    } catch {
      setError("无法访问剪贴板，可在编辑视图中选择文本复制，或下载文档。");
    }
  }
  function download() {
    const url = URL.createObjectURL(
      new Blob([current.content], { type: "text/markdown;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    const safeTitle = [...current.title]
      .map((character) =>
        character.charCodeAt(0) < 32 || '<>:"/\\|?*'.includes(character) ? "_" : character,
      )
      .join("");
    anchor.download = `${safeTitle.slice(0, 90) || "文档"}.md`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice("已下载 Markdown 文档");
  }
  return (
    <aside className="aw-preview" aria-label="文档预览" hidden={!open}>
      <div className="aw-preview-toolbar">
        <span className="aw-preview-name">
          <FileText size={16} />
          <span>{current.title}</span>
        </span>
        <div className="aw-inline-actions">
          <button
            className="aw-icon"
            title="复制文档"
            aria-label="复制文档"
            onClick={() => void copy()}
          >
            <Copy />
          </button>
          <button className="aw-icon" title="下载文档" aria-label="下载文档" onClick={download}>
            <Download />
          </button>
          <button
            className="aw-icon"
            title={full ? "还原预览" : "放大预览"}
            aria-label={full ? "还原预览" : "放大预览"}
            onClick={() => setFull(!full)}
          >
            {full ? <Minimize2 /> : <Maximize2 />}
          </button>
          <button className="aw-icon" title="关闭预览" aria-label="关闭预览" onClick={onClose}>
            <X />
          </button>
        </div>
      </div>
      <div className="aw-preview-tabs" role="tablist" aria-label="文档视图">
        {(
          [
            ["document", "文档"],
            ["edit", "编辑"],
            ["changes", "修改"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            role="tab"
            id={`aw-tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`aw-panel-${key}`}
            onClick={() => setTab(key)}
          >
            {label}
            {key === "changes" && dirty ? " ·" : ""}
          </button>
        ))}
      </div>
      <div
        ref={previewScroll}
        className="aw-preview-scroll"
        onScroll={(event) => onScrollPosition?.(event.currentTarget.scrollTop)}
      >
        <section
          id="aw-panel-document"
          role="tabpanel"
          aria-labelledby="aw-tab-document"
          hidden={tab !== "document"}
        >
          <article className="aw-paper">
            <p className="aw-paper-label">
              会话文档 · 第 {current.revision} 版{dirty ? " · 有未保存修改" : ""}
            </p>
            <h2>{current.title}</h2>
            <MarkdownView text={current.content} />
          </article>
        </section>
        <section
          id="aw-panel-edit"
          role="tabpanel"
          aria-labelledby="aw-tab-edit"
          hidden={tab !== "edit"}
        >
          <div className="aw-paper aw-editor-paper">
            <label>
              文档标题
              <input
                aria-label="文档标题"
                value={current.title}
                maxLength={120}
                onChange={(event) => edit({ title: event.target.value })}
              />
            </label>
            <label className="aw-editor-label">
              正文 · Markdown
              <textarea
                aria-label="文档正文"
                maxLength={160000}
                value={current.content}
                onChange={(event) => edit({ content: event.target.value })}
              />
            </label>
          </div>
        </section>
        <section
          id="aw-panel-changes"
          role="tabpanel"
          aria-labelledby="aw-tab-changes"
          hidden={tab !== "changes"}
        >
          <div className="aw-paper">
            <p className="aw-paper-label">与最近保存的第 {current.revision} 版比较</p>
            {!dirty ? (
              <p className="aw-muted">没有未保存的修改。</p>
            ) : (
              <>
                {current.title !== current.baseTitle && (
                  <div className="aw-diff">
                    <span>标题</span>
                    <del>{current.baseTitle}</del>
                    <ins>{current.title}</ins>
                  </div>
                )}
                {(changed.removed || changed.added) && (
                  <div className="aw-diff">
                    <span>从第 {changed.start + 1} 行开始的改动</span>
                    {changed.removed && <del>{changed.removed}</del>}
                    {changed.added && <ins>{changed.added}</ins>}
                  </div>
                )}
              </>
            )}
          </div>
        </section>
      </div>
      <div className="aw-preview-footer">
        <span className="aw-muted">{dirty ? "草稿尚未保存" : "已保存在会话中"}</span>
        <button
          className="aw-text-button"
          disabled={!dirty || busy || !current.title.trim()}
          onClick={() => void save()}
        >
          {busy ? <Save /> : dirty ? <Save /> : <Check />}
          {busy ? "保存中…" : "保存修改"}
        </button>
      </div>
      {(notice || error) && (
        <p
          className={`aw-panel-notice${error ? " is-error" : ""}`}
          role={error ? "alert" : "status"}
        >
          {error || notice}
        </p>
      )}
      {conflict && (
        <div className="aw-conflict-actions">
          {discardConfirm ? (
            <>
              <span>载入将放弃当前未保存修改。</span>
              <button
                className="aw-text-button"
                disabled={busy}
                onClick={() => void reloadLatest()}
              >
                确认放弃本地修改
              </button>
              <button
                className="aw-text-button"
                disabled={busy}
                onClick={() => setDiscardConfirm(false)}
              >
                取消
              </button>
            </>
          ) : (
            <button className="aw-text-button" onClick={() => setDiscardConfirm(true)}>
              载入最新版本
            </button>
          )}
        </div>
      )}
    </aside>
  );
}
