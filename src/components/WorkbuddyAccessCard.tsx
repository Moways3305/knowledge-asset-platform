import { useCallback, useEffect, useMemo, useState } from "react";
import "./WorkbuddyAccessCard.css";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import {
  downloadWorkbuddyConnector,
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

const PUBLIC_EXAMPLE = JSON.stringify(
  { mcpServers: { kap: { type: "http", url: "https://<KAP_HOST>/mcp" } } },
  null,
  2,
);
const safeMessage = (error: unknown) =>
  error instanceof ApiError ? error.message : "操作未成功，请稍后重试";
const suggestedPlatform = (): WorkbuddyPlatform =>
  `${navigator.platform ?? ""} ${navigator.userAgent ?? ""}`.toLowerCase().includes("mac")
    ? "macos"
    : "windows";

export default function WorkbuddyAccessCard() {
  const { authMe } = useAuth();
  const isBusinessUser = authMe?.isBusinessUser ?? false;
  const [status, setStatus] = useState<WorkbuddyTokenStatusVM | null>(null);
  const [oneTime, setOneTime] = useState<WorkbuddyConfigVM | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmRegeneration, setConfirmRegeneration] = useState(false);
  const [platform, setPlatform] = useState<WorkbuddyPlatform>(suggestedPlatform);
  const [architecture, setArchitecture] = useState<WorkbuddyArchitecture>("x64");
  const [manifest, setManifest] = useState<WorkbuddyConnectorManifestVM | null>(null);
  const [loadingManifest, setLoadingManifest] = useState(false);
  const [localOpen, setLocalOpen] = useState(false);
  const [localConnectorPath, setLocalConnectorPath] = useState("");

  const loadStatus = useCallback(async () => {
    setLoadingStatus(true);
    try {
      setStatus(await fetchWorkbuddyToken());
      setError(null);
    } catch (nextError) {
      setError(safeMessage(nextError));
    } finally {
      setLoadingStatus(false);
    }
  }, []);

  useEffect(() => {
    if (isBusinessUser) void loadStatus();
  }, [isBusinessUser, loadStatus]);

  const connected = Boolean(status?.enabled && status.lastConnectedAt);
  const connectionLabel = connected
    ? "已连接"
    : oneTime
      ? "待导入"
      : status?.enabled
        ? "等待首次连接"
        : "未生成";
  const artifact = useMemo(
    () =>
      manifest?.artifacts.find(
        (item) => item.platform === platform && item.architecture === architecture,
      ) ?? null,
    [architecture, manifest, platform],
  );

  if (!isBusinessUser) return null;

  async function generateRemote() {
    setBusy(true);
    setError(null);
    setConfirmRegeneration(false);
    try {
      setOneTime(await regenerateWorkbuddyToken("remote"));
      await loadStatus();
    } catch (nextError) {
      setError(safeMessage(nextError));
    } finally {
      setBusy(false);
    }
  }
  async function revoke() {
    setBusy(true);
    try {
      await revokeWorkbuddyToken();
      setOneTime(null);
      await loadStatus();
    } catch (nextError) {
      setError(safeMessage(nextError));
    } finally {
      setBusy(false);
    }
  }
  async function copyConfig() {
    if (!oneTime) return;
    try {
      await navigator.clipboard.writeText(oneTime.mcpConfigJson);
      setCopied(true);
    } catch {
      setError("自动复制不可用，请手动复制下方配置");
    }
  }
  async function openLocalCompatibility() {
    if (manifest || loadingManifest) return;
    setLoadingManifest(true);
    try {
      setManifest(await fetchWorkbuddyConnectors());
    } catch (nextError) {
      setError(safeMessage(nextError));
    } finally {
      setLoadingManifest(false);
    }
  }
  async function generateLocal() {
    setBusy(true);
    try {
      setOneTime(
        await regenerateWorkbuddyToken(
          "local_connector",
          platform,
          localConnectorPath.trim() || undefined,
        ),
      );
      await loadStatus();
    } catch (nextError) {
      setError(safeMessage(nextError));
    } finally {
      setBusy(false);
    }
  }
  async function downloadLocal() {
    if (!artifact) return;
    try {
      const blob = await downloadWorkbuddyConnector(artifact);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = artifact.filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setError("连接器下载或完整性校验失败，请重试");
    }
  }

  return (
    <section className="wb-card" aria-label="WorkBuddy 接入">
      <header className="wb-hero">
        <div>
          <span className="wb-kicker">REMOTE MCP · WORKBUDDY 5.4.5</span>
          <h2>把你的 KAP 权限，安全地带进 WorkBuddy</h2>
          <p>无需安装连接器。短期凭证只显示一次，服务端仅保存摘要，撤销后立即失效。</p>
        </div>
        <div className="wb-signal" aria-label="KAP 到 WorkBuddy 的加密连接">
          <span>KAP /mcp</span>
          <i>TLS</i>
          <span>WorkBuddy</span>
        </div>
      </header>
      <div className="wb-status-row">
        <span className={`wb-status-pill ${connected ? "is-enabled" : ""}`}>
          {loadingStatus ? "状态加载中" : connectionLabel}
        </span>
        {status?.expiresAt && <span>有效期至 {formatBeijingTime(status.expiresAt)}</span>}
        {status?.lastConnectedAt && (
          <span>最近连接 {formatBeijingTime(status.lastConnectedAt)}</span>
        )}
        {status?.enabled && (
          <button type="button" onClick={revoke} disabled={busy}>
            撤销
          </button>
        )}
      </div>
      {error && (
        <div className="wb-error" role="alert">
          {error}
        </div>
      )}

      <ol className="wb-guide">
        <li className="wb-guide-step">
          <div className="wb-step-number">1</div>
          <div className="wb-step-body">
            <h3>生成远程连接</h3>
            <p>生成会让旧配置立即失效。Bearer 凭证与当前 KAP 用户及租户绑定。</p>
            {!confirmRegeneration ? (
              <button
                className="wb-primary-action"
                type="button"
                disabled={busy}
                onClick={() =>
                  status?.enabled || oneTime ? setConfirmRegeneration(true) : void generateRemote()
                }
              >
                {status?.enabled || oneTime ? "重新生成远程配置" : "生成远程配置"}
              </button>
            ) : (
              <div className="wb-regenerate-confirm" role="alert">
                <p>旧 token 和旧配置会立即失效，是否继续？</p>
                <button type="button" onClick={() => void generateRemote()} disabled={busy}>
                  确认重新生成
                </button>
                <button type="button" onClick={() => setConfirmRegeneration(false)}>
                  取消
                </button>
              </div>
            )}
          </div>
        </li>

        <li className="wb-guide-step">
          <div className="wb-step-number">2</div>
          <div className="wb-step-body">
            <h3>复制仅显示一次的配置</h3>
            {oneTime ? (
              <div className="wb-onetime" role="region" aria-label="WorkBuddy 配置（仅显示一次）">
                <p className="wb-warn">这段配置含个人凭证。不要截图、转发或保存到共享文档。</p>
                <textarea
                  readOnly
                  rows={9}
                  value={oneTime.mcpConfigJson}
                  aria-label="WorkBuddy MCP JSON 配置"
                />
                <button type="button" onClick={() => void copyConfig()}>
                  {copied ? "已复制" : "复制配置"}
                </button>
              </div>
            ) : (
              <div className="wb-example">
                <span>无凭证结构示例</span>
                <pre>{PUBLIC_EXAMPLE}</pre>
              </div>
            )}
          </div>
        </li>

        <li className="wb-guide-step">
          <div className="wb-step-number">3</div>
          <div className="wb-step-body">
            <h3>在 WorkBuddy 5.4.5 合并并重启</h3>
            <ol className="wb-client-steps">
              <li>打开“专家·技能·连接器” → “自定义连接器” → “配置 MCP”。</li>
              <li>
                只合并 <code>mcpServers.kap</code>，保留已有 MCP 节点并保存。
              </li>
              <li>完全退出 WorkBuddy 后重新打开；若出现信任提示，请核对地址后手动确认。</li>
            </ol>
          </div>
        </li>

        <li className="wb-guide-step">
          <div className="wb-step-number">4</div>
          <div className="wb-step-body">
            <h3>用一次只读调用完成验证</h3>
            <p>让 WorkBuddy“列出我可访问的项目”，然后刷新。只有真实鉴权请求成功才会显示已连接。</p>
            {status?.enabled && !connected && (
              <button type="button" onClick={() => void loadStatus()}>
                刷新连接状态
              </button>
            )}
          </div>
        </li>
      </ol>

      <details
        className="wb-legacy"
        open={localOpen}
        onToggle={(event) => {
          const open = event.currentTarget.open;
          setLocalOpen(open);
          if (open) void openLocalCompatibility();
        }}
      >
        <summary>兼容模式：使用本地 Connector</summary>
        <p>仅用于无法直连企业 HTTPS MCP 的受管设备。该路径继续受支持，但不再是推荐入口。</p>
        <div className="wb-local-controls">
          <select
            value={platform}
            onChange={(event) => {
              const value = event.target.value as WorkbuddyPlatform;
              setPlatform(value);
              setArchitecture(value === "windows" ? "x64" : "arm64");
            }}
          >
            <option value="windows">Windows x64</option>
            <option value="macos">macOS</option>
          </select>
          {platform === "macos" && (
            <select
              value={architecture}
              onChange={(event) => setArchitecture(event.target.value as WorkbuddyArchitecture)}
            >
              <option value="arm64">Apple Silicon</option>
              <option value="x64">Intel</option>
            </select>
          )}
          <input
            aria-label="本地连接器自定义路径"
            value={localConnectorPath}
            onChange={(event) => setLocalConnectorPath(event.target.value)}
            placeholder="可选：连接器可执行文件绝对路径"
          />
          <button
            type="button"
            disabled={!artifact || loadingManifest}
            onClick={() => void downloadLocal()}
          >
            {loadingManifest
              ? "获取安装包…"
              : artifact
                ? `下载 ${artifact.filename}`
                : "暂无安装包"}
          </button>
          <button type="button" disabled={busy} onClick={() => void generateLocal()}>
            生成本地配置
          </button>
        </div>
      </details>
    </section>
  );
}
