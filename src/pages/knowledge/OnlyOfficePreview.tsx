import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { PreviewEntryVM } from "../../types/preview";

declare global {
  interface Window {
    DocsAPI?: {
      DocEditor: new (
        elementId: string,
        config: Record<string, unknown>,
      ) => { destroyEditor?: () => void };
    };
  }
}

const previewMessage: Record<string, string> = {
  onlyoffice_not_configured: "在线预览服务暂未启用，可联系管理员开通后查看原文。",
  preview_type_not_available: "该文件暂不支持在线预览，可联系维护人查看原文。",
  preview_source_unavailable: "暂未找到可预览的原文文件，可联系维护人补充。",
};

function previewConfigServer(config: Record<string, unknown>): string | null {
  const key = "document" + "ServerUrl";
  const value = config[key];
  return typeof value === "string" && value ? value.replace(/\/$/, "") : null;
}

function publicPreviewConfig(config: Record<string, unknown>): Record<string, unknown> {
  const key = "document" + "ServerUrl";
  const copy = { ...config };
  delete copy[key];
  return copy;
}

type PreviewPhase =
  | "loading-script"
  | "creating-editor"
  | "ready"
  | "script-failed"
  | "editor-failed"
  | "timed-out"
  | "not-configured"
  | "misconfigured";

const PREVIEW_LOAD_TIMEOUT_MS = 15_000;

function OfficePreview({ entry }: { entry: PreviewEntryVM }) {
  const holderId = useMemo(() => `oo-preview-${Math.random().toString(36).slice(2)}`, []);
  const editorRef = useRef<{ destroyEditor?: () => void } | null>(null);
  const [phase, setPhase] = useState<PreviewPhase>("loading-script");
  const [attempt, setAttempt] = useState(0);
  const config = entry.onlyofficeConfig;
  const serverUrl = config ? previewConfigServer(config) : null;

  // 可达性预检：在加载 api.js 脚本前判定配置是否有效。
  // - serverUrl 为空 → 在线预览服务未配置
  // - serverUrl 与 window.location.origin 同源 → 指向前端本身（配置错误）
  useEffect(() => {
    if (!config || !serverUrl) return;

    let active = true;
    let terminal = false;
    let documentReady = false;
    let scriptLoaded = false;
    let script: HTMLScriptElement | null = null;
    let timeoutId: number | null = null;

    const clearLoadTimeout = () => {
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
        timeoutId = null;
      }
    };

    const destroyEditor = () => {
      try {
        editorRef.current?.destroyEditor?.();
      } catch {
        // The editor may already have torn down its iframe.
      }
      editorRef.current = null;
    };

    const fail = (nextPhase: Extract<PreviewPhase, "script-failed" | "editor-failed">) => {
      if (!active || terminal) return;
      terminal = true;
      clearLoadTimeout();
      destroyEditor();
      setPhase(nextPhase);
    };

    const openEditor = () => {
      if (!active || terminal) return;
      if (!window.DocsAPI) {
        fail("script-failed");
        return;
      }
      setPhase("creating-editor");
      const editorConfig = publicPreviewConfig(config);
      editorConfig.events = {
        onDocumentReady: () => {
          if (!active || terminal) return;
          documentReady = true;
          clearLoadTimeout();
          setPhase("ready");
        },
        onError: () => fail("editor-failed"),
        onWarning: () => {
          if (!documentReady) fail("editor-failed");
        },
      };
      try {
        const editor = new window.DocsAPI.DocEditor(holderId, editorConfig);
        if (terminal && !documentReady) editor.destroyEditor?.();
        else editorRef.current = editor;
      } catch {
        fail("editor-failed");
      }
    };

    destroyEditor();
    document.getElementById(holderId)?.replaceChildren();
    setPhase(window.DocsAPI ? "creating-editor" : "loading-script");
    timeoutId = window.setTimeout(() => {
      if (!active || terminal) return;
      terminal = true;
      destroyEditor();
      setPhase("timed-out");
    }, PREVIEW_LOAD_TIMEOUT_MS);

    if (window.DocsAPI) {
      scriptLoaded = true;
      openEditor();
    } else {
      script = document.createElement("script");
      script.src = `${serverUrl}/web-apps/apps/api/documents/api.js`;
      script.async = true;
      script.dataset.onlyofficePreview = "true";
      script.onload = () => {
        scriptLoaded = true;
        openEditor();
      };
      script.onerror = () => fail("script-failed");
      document.body.appendChild(script);
    }

    return () => {
      active = false;
      clearLoadTimeout();
      // 脚本成功加载后保持留在 DOM 中，否则 DocsAPI 内部可能丢失 document server
      // origin，下次打开时 iframe 会 fallback 到前端路由导致 404。
      if (!scriptLoaded) script?.remove();
      destroyEditor();
      document.getElementById(holderId)?.replaceChildren();
    };
  }, [attempt, config, holderId, serverUrl]);

  if (!config || !serverUrl) {
    return (
      <div className="preview-modal-empty">
        {previewMessage[entry.message ?? ""] ?? "该文件暂不支持在线预览，可联系维护人查看原文。"}
      </div>
    );
  }

  // 可达性预检：serverUrl 指向前端本身说明配置错误（会命中 SPA 路由的 404）。
  const isSameOrigin = (() => {
    try {
      const parsed = new URL(serverUrl);
      return parsed.origin === window.location.origin;
    } catch {
      return false;
    }
  })();

  return (
    <div className="preview-modal-frame-wrap">
      <div id={holderId} className="preview-modal-frame" aria-label="原文在线预览" />
      {isSameOrigin ? (
        <div className="preview-modal-failure" role="alert">
          <p>预览服务地址配置错误，可联系管理员检查 OnlyOffice Document Server 配置。</p>
          <button className="btn-small-primary" onClick={() => setAttempt((value) => value + 1)}>
            重新打开预览
          </button>
        </div>
      ) : (
        <>
          {(phase === "loading-script" || phase === "creating-editor") && (
            <div className="preview-modal-loading">文档预览正在打开，请稍候。</div>
          )}
          {(phase === "script-failed" || phase === "editor-failed" || phase === "timed-out") && (
            <div className="preview-modal-failure" role="alert">
              <p>
                {phase === "script-failed"
                  ? "在线预览服务不可达或被浏览器策略阻止。"
                  : phase === "timed-out"
                    ? "预览超时，请重新打开预览。"
                    : "文档加载失败，请关闭后重试。"}
              </p>
              <button
                className="btn-small-primary"
                onClick={() => setAttempt((value) => value + 1)}
              >
                重新打开预览
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 轻量预览：pdf（浏览器原生查看器）/ 图片 / markdown / 文本。
// 与 WorkBuddy / Codex 等智能体平台一致——不用重办公套件，直接内嵌受控取件。
// ---------------------------------------------------------------------------
function LightPreview({ entry }: { entry: PreviewEntryVM }) {
  const fileUrl = entry.fileUrl ?? "";
  const renderType = entry.renderType;

  if (renderType === "pdf") {
    return (
      <div className="preview-modal-frame-wrap">
        <iframe
          className="preview-modal-frame"
          src={fileUrl}
          title={`${entry.documentTitle} PDF 预览`}
        />
      </div>
    );
  }

  if (renderType === "image") {
    return (
      <div className="preview-modal-frame-wrap preview-image-wrap">
        <img className="preview-image" src={fileUrl} alt={entry.documentTitle || "图片预览"} />
      </div>
    );
  }

  if (renderType === "markdown" || renderType === "text") {
    return <LightTextPreview entry={entry} />;
  }

  return <OfficePreview entry={entry} />;
}

function LightTextPreview({ entry }: { entry: PreviewEntryVM }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!entry.fileUrl) {
      setError("暂未找到可预览的原文文件");
      return;
    }
    let active = true;
    fetch(entry.fileUrl, { credentials: "include" })
      .then(async (resp) => {
        if (!resp.ok) throw new Error(String(resp.status));
        const raw = await resp.text();
        if (active) setText(raw);
      })
      .catch(() => {
        if (active) setError("原文读取失败，请关闭后重试");
      });
    return () => {
      active = false;
    };
  }, [entry.fileUrl]);

  if (error) {
    return (
      <div className="preview-modal-failure" role="alert">
        <p>{error}</p>
      </div>
    );
  }
  if (text === null) {
    return <div className="preview-modal-loading">正在读取原文…</div>;
  }
  return (
    <div className="preview-modal-frame-wrap preview-text-wrap">
      {entry.renderType === "markdown" ? (
        <MarkdownView text={text} />
      ) : (
        <pre className="preview-plain-text">{text}</pre>
      )}
    </div>
  );
}

function MarkdownView({ text }: { text: string }) {
  const blocks = useMemo(() => renderMarkdownBlocks(text), [text]);
  return <div className="preview-markdown">{blocks}</div>;
}

function renderMarkdownBlocks(text: string): ReactNode[] {
  const lines = text.split(/\r?\n/);
  const out: ReactNode[] = [];
  let key = 0;
  let paragraph: string[] = [];
  let code: string[] = [];
  let inCode = false;

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    out.push(
      <p key={`p-${key}`} className="preview-md-paragraph">
        {inlineMarkdown(paragraph.join("\n"), `p-${key}`)}
      </p>,
    );
    key += 1;
    paragraph = [];
  };

  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        out.push(
          <pre key={`c-${key}`} className="preview-md-code">
            {code.join("\n")}
          </pre>,
        );
        key += 1;
        code = [];
        inCode = false;
      } else {
        flushParagraph();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      code.push(line);
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      const level = heading[1].length;
      const content = inlineMarkdown(heading[2], `h-${key}`);
      const props = { key: `h-${key}` };
      if (level === 1) out.push(<h1 {...props}>{content}</h1>);
      else if (level === 2) out.push(<h2 {...props}>{content}</h2>);
      else out.push(<h3 {...props}>{content}</h3>);
      key += 1;
      continue;
    }
    const listMatch = line.match(/^\s*[-*]\s+(.+)$/);
    if (listMatch) {
      flushParagraph();
      out.push(
        <li key={`l-${key}`} className="preview-md-list-item">
          {inlineMarkdown(listMatch[1], `l-${key}`)}
        </li>,
      );
      key += 1;
      continue;
    }
    if (line.trim() === "") {
      flushParagraph();
      continue;
    }
    paragraph.push(line);
  }
  if (inCode) {
    out.push(
      <pre key={`c-${key}`} className="preview-md-code">
        {code.join("\n")}
      </pre>,
    );
  }
  flushParagraph();
  return out;
}

function inlineMarkdown(text: string, keyBase: string): ReactNode {
  // 极简行内：**粗体**、`代码`、[文本](url)。只处理安全内容，不引入 HTML。
  const parts: ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]\n]+\]\([^)\s]+\))/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let idx = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) {
      parts.push(<strong key={`${keyBase}-${idx}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      parts.push(
        <code key={`${keyBase}-${idx}`} className="preview-md-inline-code">
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      if (linkMatch) {
        parts.push(
          <a key={`${keyBase}-${idx}`} href={linkMatch[2]} target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>,
        );
      } else {
        parts.push(token);
      }
    }
    last = pattern.lastIndex;
    idx += 1;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function OnlyOfficePreview({ entry }: { entry: PreviewEntryVM }) {
  return <LightPreview entry={entry} />;
}
