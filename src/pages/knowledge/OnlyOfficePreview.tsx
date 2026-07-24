import { useEffect, useMemo, useRef, useState } from "react";
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

export function OnlyOfficePreview({ entry }: { entry: PreviewEntryVM }) {
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
