import { useCallback, useEffect, useMemo, useState } from "react";
import "./WorkbuddyAccessCard.css";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import {
  fetchWorkbuddyConnectors,
  fetchWorkbuddyToken,
  regenerateWorkbuddyToken,
  revokeWorkbuddyToken,
  type WorkbuddyArchitecture,
  type WorkbuddyConfigVM,
  type WorkbuddyConnectorManifestVM,
  type WorkbuddyPlatform,
  type WorkbuddyTokenStatusVM,
} from "../api/workbuddy";
import { formatBeijingTime } from "../utils/time";

const DESCRIPTION =
  "WorkBuddy 仅可读取你有权限的待办、最近知识、项目知识与简报、待审核事项和原文访问状态，不具备写入或越权访问能力。";

function safeMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "操作未成功，请稍后重试";
}

export default function WorkbuddyAccessCard() {
  const { authMe } = useAuth();
  const isBusinessUser = authMe?.isBusinessUser ?? false;
  const [platform, setPlatform] = useState<WorkbuddyPlatform>("windows");
  const [macArchitecture, setMacArchitecture] = useState<WorkbuddyArchitecture>("arm64");
  const [status, setStatus] = useState<WorkbuddyTokenStatusVM | null>(null);
  const [manifest, setManifest] = useState<WorkbuddyConnectorManifestVM | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingManifest, setLoadingManifest] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [oneTime, setOneTime] = useState<WorkbuddyConfigVM | null>(null);
  const [importAcknowledged, setImportAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);

  const loadStatus = useCallback(async () => {
    setLoadingStatus(true);
    setError(null);
    try {
      setStatus(await fetchWorkbuddyToken());
    } catch (nextError) {
      setError(safeMessage(nextError));
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  const loadManifest = useCallback(async () => {
    setLoadingManifest(true);
    setDownloadError(null);
    try {
      setManifest(await fetchWorkbuddyConnectors());
    } catch (nextError) {
      setManifest(null);
      setDownloadError(safeMessage(nextError));
    } finally {
      setLoadingManifest(false);
    }
  }, []);

  useEffect(() => {
    if (!isBusinessUser) return;
    void loadStatus();
    void loadManifest();
  }, [isBusinessUser, loadManifest, loadStatus]);

  const architecture = platform === "windows" ? "x64" : macArchitecture;
  const artifact = useMemo(
    () =>
      manifest?.artifacts.find(
        (item) => item.platform === platform && item.architecture === architecture,
      ) ?? null,
    [architecture, manifest, platform],
  );

  if (!isBusinessUser) return null;

  async function onGenerate() {
    setBusy(true);
    setError(null);
    setCopied(false);
    setImportAcknowledged(false);
    try {
      const config = await regenerateWorkbuddyToken(platform);
      setOneTime(config);
      await loadStatus();
    } catch (nextError) {
      setError(safeMessage(nextError));
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
      setImportAcknowledged(false);
      await loadStatus();
    } catch (nextError) {
      setError(safeMessage(nextError));
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
      setCopied(false);
      setError("自动复制不可用，请手动选择下方配置文本复制。");
    }
  }

  async function onCheckConnection() {
    setImportAcknowledged(true);
    await loadStatus();
  }

  const enabled = status?.enabled ?? false;
  const connected = Boolean(enabled && status?.lastConnectedAt);
  const connectionLabel = connected
    ? "已连接"
    : oneTime && !importAcknowledged
      ? "待导入"
      : enabled
        ? "等待首次连接"
        : "未生成";

  return (
    <section className="wb-card" aria-label="WorkBuddy 接入">
      <div className="wb-integration-head">
        <div>
          <span className={`wb-status-pill ${connected ? "is-enabled" : ""}`}>
            {loadingStatus ? "状态加载中" : connectionLabel}
          </span>
          <p>{DESCRIPTION}</p>
          {connected && status?.lastConnectedAt && (
            <p className="wb-last-connected">
              最近连接：{formatBeijingTime(status.lastConnectedAt)}
            </p>
          )}
        </div>
        {enabled && (
          <button className="wb-secondary-action" type="button" onClick={onRevoke} disabled={busy}>
            撤销配置
          </button>
        )}
      </div>

      {error && (
        <div className="wb-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void loadStatus()} disabled={loadingStatus}>
            重试
          </button>
        </div>
      )}

      <ol className="wb-guide">
        <li className="wb-guide-step">
          <div className="wb-step-number">1</div>
          <div className="wb-step-body">
            <h3>安装 KAP 连接器</h3>
            <p>选择你的电脑平台。安装包已包含运行环境，无需安装 Python 或其他依赖。</p>
            <fieldset className="wb-platforms" disabled={busy || Boolean(oneTime)}>
              <legend className="sr-only">电脑平台</legend>
              <label>
                <input
                  type="radio"
                  name="workbuddy-platform"
                  value="windows"
                  checked={platform === "windows"}
                  onChange={() => setPlatform("windows")}
                />
                Windows 10/11 x64
              </label>
              <label>
                <input
                  type="radio"
                  name="workbuddy-platform"
                  value="macos"
                  checked={platform === "macos"}
                  onChange={() => setPlatform("macos")}
                />
                macOS
              </label>
            </fieldset>
            {platform === "macos" && (
              <label className="wb-architecture">
                Mac 芯片
                <select
                  value={macArchitecture}
                  disabled={busy || Boolean(oneTime)}
                  onChange={(event) =>
                    setMacArchitecture(event.target.value as WorkbuddyArchitecture)
                  }
                >
                  <option value="arm64">Apple Silicon（M 系列）</option>
                  <option value="x64">Intel</option>
                </select>
              </label>
            )}
            {loadingManifest ? (
              <p>正在获取安装包…</p>
            ) : artifact ? (
              <div className="wb-download">
                <a href={artifact.downloadUrl}>
                  下载 {platform === "windows" ? "Windows" : "macOS"} 连接器
                </a>
                <span>版本 {artifact.version}</span>
                <code title={artifact.sha256}>SHA-256 {artifact.sha256.slice(0, 12)}…</code>
                {artifact.releaseStatus === "internal" && <span>内部测试候选物</span>}
              </div>
            ) : (
              <div className="wb-inline-recovery">
                <span>{downloadError ?? "该平台安装包暂不可用"}</span>
                <button type="button" onClick={() => void loadManifest()}>
                  重新获取
                </button>
              </div>
            )}
            <p>完成安装后关闭并重新打开 WorkBuddy，再继续生成个人配置。</p>
          </div>
        </li>

        <li className="wb-guide-step">
          <div className="wb-step-number">2</div>
          <div className="wb-step-body">
            <h3>生成并导入个人配置</h3>
            <p>
              在 WorkBuddy 打开“设置 → MCP 服务 → 导入配置”，粘贴下方完整内容并保存。
              选择平台或下载安装包不会轮换旧 token；只有点击生成或重置才会使旧配置失效。
            </p>
            <div className="wb-actions">
              <button
                type="button"
                onClick={onGenerate}
                disabled={busy || loadingStatus || !artifact}
              >
                {enabled ? "重置并生成配置" : "生成个人配置"}
              </button>
            </div>
            {oneTime && (
              <div className="wb-onetime" role="region" aria-label="WorkBuddy 配置（仅显示一次）">
                <p className="wb-warn">
                  此配置含一次性展示的个人凭证，请立即导入；不要转发或保存到共享文档。
                </p>
                <textarea
                  className="wb-config"
                  readOnly
                  rows={9}
                  value={oneTime.mcpConfigJson}
                  aria-label={`${oneTime.platform === "windows" ? "Windows" : "macOS"} mcp.json 配置`}
                />
                <div className="wb-actions">
                  <button type="button" onClick={onCopy} disabled={busy}>
                    复制配置
                  </button>
                  {copied && <span className="wb-copied">已复制</span>}
                </div>
              </div>
            )}
          </div>
        </li>

        <li className="wb-guide-step">
          <div className="wb-step-number">3</div>
          <div className="wb-step-body">
            <h3>验证首次连接</h3>
            <p>
              在 WorkBuddy 中调用一次 KAP 工具，例如“列出我可访问的项目”，成功后这里才会显示已连接。
            </p>
            <div className="wb-connection-state" aria-live="polite">
              <strong>{connectionLabel}</strong>
              {connected && status?.lastConnectedAt && (
                <span>{formatBeijingTime(status.lastConnectedAt)}</span>
              )}
            </div>
            {enabled && !connected && (
              <div className="wb-actions">
                <button type="button" onClick={onCheckConnection} disabled={loadingStatus}>
                  {oneTime && !importAcknowledged ? "我已导入，检查连接" : "刷新连接状态"}
                </button>
                <span className="wb-help-text">
                  仍未连接？确认连接器已安装、WorkBuddy 已重启，并重新导入当前配置。
                </span>
              </div>
            )}
          </div>
        </li>
      </ol>
    </section>
  );
}
