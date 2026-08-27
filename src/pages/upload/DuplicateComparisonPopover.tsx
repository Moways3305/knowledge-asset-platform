import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { UploadDuplicateDTO } from "../../types/ingest";

const labels = {
  exact_content: "内容完全相同",
  same_batch: "本批内容相同",
  suspected_metadata: "命名信息疑似重复",
  none: "",
} as const;

function formatBytes(value: number | null | undefined) {
  if (value == null) return "未提供";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}

export default function DuplicateComparisonPopover({
  duplicate,
  current,
  busy = false,
  onSkip,
  onIndependent,
  onKeep,
}: {
  duplicate: UploadDuplicateDTO | null | undefined;
  current: {
    fileName: string;
    fileSize?: number | null;
    scopeLabel?: string;
    directory?: string | null;
    subject?: string | null;
    formedOn?: string | null;
    version?: string | null;
  };
  busy?: boolean;
  onSkip?: () => void;
  onIndependent?: () => void;
  onKeep?: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const suppressNextFocusOpenRef = useRef(false);
  const panelId = useId();
  const open = pinned || hovered || focused;

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setPinned(false);
      setHovered(false);
      setFocused(false);
      suppressNextFocusOpenRef.current = true;
      triggerRef.current?.focus();
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [open]);

  if (!duplicate || duplicate.duplicate_state === "none") return null;
  const candidate = duplicate.preferred_candidate;
  const restricted = duplicate.match_type === "restricted_match";
  const label =
    duplicate.duplicate_state === "same_batch" && candidate?.same_batch_ordinal != null
      ? `本批第 ${candidate.same_batch_ordinal + 1} 项相同`
      : labels[duplicate.duplicate_state];

  return (
    <div
      className="upload-duplicate"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocusCapture={() => {
        if (suppressNextFocusOpenRef.current) {
          suppressNextFocusOpenRef.current = false;
          return;
        }
        setFocused(true);
      }}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(false);
      }}
    >
      <span className={`upload-duplicate-label is-${duplicate.duplicate_state}`}>{label}</span>
      <button
        ref={triggerRef}
        type="button"
        className="upload-duplicate-trigger"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setPinned((value) => !value)}
      >
        对比
      </button>
      {open && (
        <section
          className="upload-duplicate-popover"
          id={panelId}
          role="dialog"
          aria-label={`${current.fileName} 重复资料对比`}
        >
          {restricted ? (
            <div className="upload-duplicate-restricted" role="status">
              已存在相同资料，详情受限。系统不会显示标题、项目、摘要或内部标识。
            </div>
          ) : (
            <div className="upload-duplicate-columns">
              <div>
                <h4>本次文件</h4>
                <dl>
                  <div>
                    <dt>文件名</dt>
                    <dd>{current.fileName}</dd>
                  </div>
                  <div>
                    <dt>大小</dt>
                    <dd>{formatBytes(current.fileSize)}</dd>
                  </div>
                  <div>
                    <dt>目标</dt>
                    <dd>{current.scopeLabel ?? "当前目标库"}</dd>
                  </div>
                  <div>
                    <dt>目录</dt>
                    <dd>{current.directory || "待确认"}</dd>
                  </div>
                  <div>
                    <dt>主题</dt>
                    <dd>{current.subject || "待确认"}</dd>
                  </div>
                  <div>
                    <dt>形成日期</dt>
                    <dd>{current.formedOn || "待确认"}</dd>
                  </div>
                  <div>
                    <dt>版本</dt>
                    <dd>{current.version || "待确认"}</dd>
                  </div>
                </dl>
              </div>
              <div>
                <h4>已有资料</h4>
                {duplicate.duplicate_state === "same_batch" ? (
                  <p>本次上传的第 {(candidate?.same_batch_ordinal ?? 0) + 1} 项内容完全相同。</p>
                ) : (
                  <dl>
                    <div>
                      <dt>标题</dt>
                      <dd>{candidate?.title || "未提供"}</dd>
                    </div>
                    <div>
                      <dt>范围</dt>
                      <dd>{candidate?.scope_label || "当前目标库"}</dd>
                    </div>
                    <div>
                      <dt>目录</dt>
                      <dd>{candidate?.directory_key || "未分类"}</dd>
                    </div>
                    <div>
                      <dt>形成日期</dt>
                      <dd>{candidate?.formed_on || "未提供"}</dd>
                    </div>
                    <div>
                      <dt>版本</dt>
                      <dd>{candidate?.version || "未提供"}</dd>
                    </div>
                    <div>
                      <dt>状态</dt>
                      <dd>{candidate?.asset_status || "待确认"}</dd>
                    </div>
                    <div>
                      <dt>安全摘要</dt>
                      <dd>{candidate?.safe_summary || "无可显示摘要"}</dd>
                    </div>
                  </dl>
                )}
                {candidate?.can_view_detail && candidate.asset_id && (
                  <Link to={`/knowledge/${candidate.asset_id}`} target="_blank" rel="noreferrer">
                    查看详情
                  </Link>
                )}
              </div>
            </div>
          )}
          {(onSkip || onIndependent || onKeep) && (
            <div className="upload-duplicate-actions">
              {onKeep &&
                duplicate.duplicate_state === "same_batch" &&
                !duplicate.default_selected && (
                  <button type="button" disabled={busy} onClick={onKeep}>
                    设为本批保留项
                  </button>
                )}
              {onSkip && (
                <button type="button" disabled={busy} onClick={onSkip}>
                  本次不入库
                </button>
              )}
              {onIndependent && (
                <button type="button" disabled={busy} onClick={onIndependent}>
                  仍作为独立资料入库
                </button>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
