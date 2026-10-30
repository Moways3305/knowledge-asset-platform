import { useEffect, useState } from "react";
import { ApiError, apiDelete, apiGet } from "../api/http";
import { PageSection } from "./ProductLayout";
import "./McpOAuth.css";
import Button from "./Button";
import ConfirmDialog from "./ConfirmDialog";

interface Grant {
  id: string;
  name: string;
  operations_enabled: boolean;
  expires_at: string;
}

export default function McpOAuthGrants() {
  const [items, setItems] = useState<Grant[]>([]);
  const [error, setError] = useState("");
  const [available, setAvailable] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<Grant | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    apiGet<{ items: Grant[] }>("/api/v1/auth/mcp-oauth/grants")
      .then((data) => {
        if (active) {
          setItems(data.items);
          setAvailable(true);
        }
      })
      .catch((e: unknown) => {
        if (active && !(e instanceof ApiError && e.status === 503)) {
          setAvailable(true);
          setError(e instanceof Error ? e.message : "应用授权加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, []);
  async function revoke(id: string) {
    if (busy) return;
    setError("");
    setBusy(true);
    try {
      await apiDelete(`/api/v1/auth/mcp-oauth/grants/${encodeURIComponent(id)}`);
      setItems((current) => current.filter((item) => item.id !== id));
      setRevokeTarget(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤销失败");
    } finally {
      setBusy(false);
    }
  }
  if (!available) return null;
  return (
    <PageSection
      className="mcp-oauth-grants"
      title="已授权应用"
      description="OAuth 登录授权与上方的手动凭证配置相互独立。"
    >
      {error && <p role="alert">{error}</p>}
      {!items.length && <p>暂无应用授权。在智能体的 MCP 接入口选择 OAuth，再登录 KAP 确认授权。</p>}
      {items.map((item) => (
        <div key={item.id}>
          <p>
            {item.name} · {item.operations_enabled ? "查询及操作" : "只读查询"} · 到期：
            {new Date(item.expires_at).toLocaleString()}
          </p>
          <Button
            variant="danger"
            size="small"
            disabled={busy}
            onClick={() => {
              setError("");
              setRevokeTarget(item);
            }}
          >
            撤销此应用授权
          </Button>
        </div>
      ))}
      <ConfirmDialog
        open={!!revokeTarget}
        title={`撤销“${revokeTarget?.name ?? ""}”的应用授权？`}
        description="此应用将不能再通过该授权访问 KAP，手动配置凭证和其他应用授权不受影响。"
        confirmText="确认撤销应用授权"
        danger
        busy={busy}
        error={error}
        errorDescription={error}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => revokeTarget && void revoke(revokeTarget.id)}
      />
    </PageSection>
  );
}
