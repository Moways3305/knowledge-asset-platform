import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { apiGet, apiPost } from "../api/http";
import { ProductPage, PageHeader, PageSection } from "../components/ProductLayout";
import "../components/McpOAuth.css";

interface ConsentView {
  client_name: string;
  redirect_origin: string;
  operations_requested: boolean;
}

export default function McpAuthorizePage() {
  const [params] = useSearchParams();
  const requestId = params.get("request");
  const [view, setView] = useState<ConsentView | null>(null);
  const [error, setError] = useState("");
  const [operations, setOperations] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setView(null);
    setOperations(false);
    if (!requestId) {
      setError("缺少授权请求，请回到智能体重新连接。");
      return;
    }
    setError("");
    apiGet<ConsentView>(`/api/v1/auth/mcp-oauth/requests/${encodeURIComponent(requestId)}`)
      .then((value) => {
        if (active) setView(value);
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : "授权请求加载失败");
      });
    return () => {
      active = false;
    };
  }, [requestId]);

  async function decide(approved: boolean) {
    if (!view || !requestId || busy) return;
    setBusy(true);
    try {
      const result = await apiPost<{ redirect_url: string }>(
        `/api/v1/auth/mcp-oauth/requests/${encodeURIComponent(requestId)}`,
        { approved, operations },
      );
      window.location.assign(result.redirect_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "授权未完成，请重新连接");
      setBusy(false);
    }
  }

  return (
    <ProductPage className="mcp-oauth-consent">
      <PageHeader
        title="授权智能体访问 KAP"
        description="请核对应用和回调域名。授权不会扩大你的资料访问权限。"
      />
      <PageSection title="本次连接">
        {error && <p role="alert">{error}</p>}
        {!view && !error && <p role="status">正在读取授权请求…</p>}
        {view && (
          <>
            <p>应用名称：{view.client_name}（由应用自行填写）</p>
            <p>返回地址：{view.redirect_origin}</p>
            <p>允许查询你有权限访问的知识、项目和待办。</p>
            {view.operations_requested && (
              <label>
                <input
                  type="checkbox"
                  checked={operations}
                  onChange={(e) => setOperations(e.target.checked)}
                />
                同意开放上传、入库确认和审批接口；每次业务操作仍需我的明确授权。
              </label>
            )}
            <p>授权最长有效 30 天，可在「MCP 接入」中撤销。请勿授权不认识的应用。</p>
            <div className="mcp-oauth-actions">
              <button
                type="button"
                className="mcp-oauth-primary"
                disabled={busy || (view.operations_requested && !operations)}
                onClick={() => void decide(true)}
              >
                同意并连接
              </button>
              <button type="button" disabled={busy} onClick={() => void decide(false)}>
                拒绝授权
              </button>
            </div>
          </>
        )}
      </PageSection>
    </ProductPage>
  );
}
