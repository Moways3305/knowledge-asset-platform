import { useCallback, useEffect, useState } from "react";
import "./WorkbuddyAccessCard.css";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import {
  fetchWorkbuddyToken,
  regenerateWorkbuddyToken,
  revokeWorkbuddyToken,
  type WorkbuddyConfigVM,
  type WorkbuddyTokenStatusVM,
} from "../api/workbuddy";
import { SettingsRow } from "./ProductLayout";

const DESCRIPTION = "连接 WorkBuddy 后，它只能访问你在平台内有权限的知识。";

// 安全文案：不暴露后端路径 / HTTP code / denied_reason；ApiError.message 已是安全文案。
function safeMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "操作未成功，请稍后重试";
}

/**
 * WorkBuddy 自助接入卡片。仅对在职业务用户显示（pure admin / 非业务用户不渲染入口）。
 * 生成 / 重置成功后一次性展示 token 与可复制的 mcp.json；token 只显示一次。
 */
export default function WorkbuddyAccessCard() {
  const { authMe } = useAuth();
  const isBusinessUser = authMe?.isBusinessUser ?? false;

  const [status, setStatus] = useState<WorkbuddyTokenStatusVM | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 一次性配置（仅在本次生成 / 重置后内存中存在；刷新即消失，不持久化）。
  const [oneTime, setOneTime] = useState<WorkbuddyConfigVM | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await fetchWorkbuddyToken());
    } catch (err) {
      setError(safeMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isBusinessUser) void load();
  }, [isBusinessUser, load]);

  // 非业务用户 / pure admin：不显示入口（而非加载失败）。
  if (!isBusinessUser) return null;

  async function onGenerate() {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const cfg = await regenerateWorkbuddyToken();
      setOneTime(cfg);
      await load();
    } catch (err) {
      setError(safeMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke() {
    setBusy(true);
    setError(null);
    try {
      await revokeWorkbuddyToken();
      setOneTime(null);
      await load();
    } catch (err) {
      setError(safeMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function onCopy() {
    if (!oneTime) return;
    try {
      await navigator.clipboard.writeText(oneTime.mcpConfigJson);
      setCopied(true);
    } catch {
      // 剪贴板不可用（无 HTTPS / 权限）：提示用户手动复制下方文本框。
      setCopied(false);
      setError("自动复制不可用，请手动选择下方配置文本复制。");
    }
  }

  const enabled = status?.enabled ?? false;

  return (
    <section className="wb-card" aria-label="WorkBuddy 接入">
      <SettingsRow
        title="WorkBuddy 接入"
        description={
          loading
            ? "正在加载接入状态…"
            : `${DESCRIPTION}${enabled ? " 当前已启用。" : " 当前未启用。"}`
        }
        control={
          <div className="wb-actions">
            <button type="button" onClick={onGenerate} disabled={busy || loading}>
              {enabled ? "重置配置" : "生成配置"}
            </button>
            {enabled && (
              <button type="button" onClick={onRevoke} disabled={busy}>
                撤销配置
              </button>
            )}
          </div>
        }
      />

      {error && (
        <p className="wb-error" role="alert">
          {error}
        </p>
      )}

      {oneTime && (
        <div className="wb-onetime" role="region" aria-label="WorkBuddy 配置（仅显示一次）">
          <p className="wb-warn">
            ⚠️ 这串 token 只显示一次，请立即复制保存。重置后旧配置立即失效。
          </p>
          <textarea
            className="wb-config"
            readOnly
            rows={10}
            value={oneTime.mcpConfigJson}
            aria-label="mcp.json 配置"
          />
          <div className="wb-actions">
            <button type="button" onClick={onCopy} disabled={busy}>
              复制配置
            </button>
            {copied && <span className="wb-copied">已复制</span>}
          </div>
        </div>
      )}
    </section>
  );
}
