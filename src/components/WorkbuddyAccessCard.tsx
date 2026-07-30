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

const DEFAULT_COMMANDS: Record<WorkbuddyPlatform, string> = {
  windows: String.raw`C:\Program Files\KAP WorkBuddy Connector\kap-workbuddy-connector.exe`,
  macos: "/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector",
};

function suggestedPlatform(): WorkbuddyPlatform {
  const hint = `${navigator.platform ?? ""} ${navigator.userAgent ?? ""}`.toLowerCase();
  return hint.includes("mac") ? "macos" : "windows";
}

function safeMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "操作未成功，请稍后重试";
}

function validateCustomPath(platform: WorkbuddyPlatform, path: string): string | null {
  if (!path) return "请输入连接器可执行文件的完整路径";
  if (path !== path.trim() || [...path].some((char) => char.charCodeAt(0) < 32)) {
    return "路径首尾不能有空白，也不能包含换行或控制字符";
  }
  if (platform === "windows") {
    const reservedNames = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i;
    const segments = path.length >= 3 ? path.slice(3).split("\\") : [];
    const invalidSegment = segments.some(
      (segment) =>
        !segment ||
        /[<>:"/|?*]/.test(segment) ||
        segment.endsWith(" ") ||
        segment.endsWith(".") ||
        reservedNames.test(segment),
    );
    if (!/^[A-Za-z]:\\.+\.exe$/i.test(path) || invalidSegment) {
      return String.raw`Windows 路径应为盘符开头、以 .exe 结尾的绝对路径，例如 C:\Apps\kap-workbuddy-connector.exe`;
    }
  } else if (!path.startsWith("/") || path.includes("\\") || path.toLowerCase().endsWith(".exe")) {
    return "macOS 路径应为以 / 开头的 POSIX 可执行文件绝对路径";
  }
  return null;
}

export default function WorkbuddyAccessCard() {
  const { authMe } = useAuth();
  const isBusinessUser = authMe?.isBusinessUser ?? false;
  const [platform, setPlatform] = useState<WorkbuddyPlatform>(suggestedPlatform);
  const [macArchitecture, setMacArchitecture] = useState<WorkbuddyArchitecture>("arm64");
  const [pathMode, setPathMode] = useState<"default" | "custom">("default");
  const [customPath, setCustomPath] = useState("");
  const [status, setStatus] = useState<WorkbuddyTokenStatusVM | null>(null);
  const [manifest, setManifest] = useState<WorkbuddyConnectorManifestVM | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingManifest, setLoadingManifest] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [oneTime, setOneTime] = useState<WorkbuddyConfigVM | null>(null);
  const [confirmRegeneration, setConfirmRegeneration] = useState(false);
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
  const customPathError = pathMode === "custom" ? validateCustomPath(platform, customPath) : null;
  const selectedCommand = pathMode === "custom" ? customPath : DEFAULT_COMMANDS[platform];
  const enabled = status?.enabled ?? false;
  const connected = Boolean(enabled && status?.lastConnectedAt);
  const connectionLabel = connected
    ? "已连接"
    : oneTime && !importAcknowledged
      ? "待配置"
      : enabled
        ? "等待首次连接"
        : "未生成";

  if (!isBusinessUser) return null;

  async function performGenerate() {
    setBusy(true);
    setError(null);
    setCopied(false);
    setImportAcknowledged(false);
    setConfirmRegeneration(false);
    try {
      const config = await regenerateWorkbuddyToken(
        platform,
        pathMode === "custom" ? customPath : undefined,
      );
      setOneTime(config);
      await loadStatus();
    } catch (nextError) {
      setError(safeMessage(nextError));
    } finally {
      setBusy(false);
    }
  }

  function onGenerate() {
    if (enabled || oneTime) {
      setConfirmRegeneration(true);
      return;
    }
    void performGenerate();
  }

  async function onRevoke() {
    setBusy(true);
    setError(null);
    try {
      await revokeWorkbuddyToken();
      setOneTime(null);
      setConfirmRegeneration(false);
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
      setError("自动复制不可用，请手动选择下方配置文本复制");
    }
  }

  async function onCheckConnection() {
    setImportAcknowledged(true);
    await loadStatus();
  }

  return (
    <section className="wb-card" aria-label="WorkBuddy 接入">
      <div className="wb-integration-head">
        <div>
          <span className={`wb-status-pill ${connected ? "is-enabled" : ""}`}>
            {loadingStatus ? "状态加载中" : connectionLabel}
          </span>
          <p>
            WorkBuddy 仅可读取你在 KAP
            中有权访问的内容。平台、下载安装或复制操作都不会被视为已连接。
          </p>
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
            <h3>确认平台并安装 KAP 连接器</h3>
            <p>已根据当前浏览器提供的信息预选平台，仅作为建议。请在下载和生成前亲自确认。</p>
            <fieldset className="wb-platforms" disabled={busy}>
              <legend className="sr-only">目标电脑平台</legend>
              <label>
                <input
                  type="radio"
                  name="workbuddy-platform"
                  checked={platform === "windows"}
                  onChange={() => {
                    setPlatform("windows");
                    setConfirmRegeneration(false);
                  }}
                />
                Windows 10/11 x64
              </label>
              <label>
                <input
                  type="radio"
                  name="workbuddy-platform"
                  checked={platform === "macos"}
                  onChange={() => {
                    setPlatform("macos");
                    setConfirmRegeneration(false);
                  }}
                />
                macOS
              </label>
            </fieldset>
            {platform === "macos" && (
              <label className="wb-architecture">
                Mac 芯片架构
                <select
                  value={macArchitecture}
                  disabled={busy}
                  onChange={(event) => {
                    setMacArchitecture(event.target.value as WorkbuddyArchitecture);
                    setConfirmRegeneration(false);
                  }}
                >
                  <option value="arm64">Apple Silicon（arm64）</option>
                  <option value="x64">Intel（x64）</option>
                </select>
              </label>
            )}
            {loadingManifest ? (
              <p>正在获取安装包…</p>
            ) : artifact ? (
              <div className="wb-download">
                <a href={artifact.downloadUrl}>下载 {artifact.filename}</a>
                <span>
                  {platform === "windows" ? "Windows" : "macOS"} · {architecture} · 版本{" "}
                  {artifact.version}
                </span>
                <code title={artifact.sha256}>SHA-256 {artifact.sha256.slice(0, 12)}…</code>
                {artifact.releaseStatus === "internal" && (
                  <p className="wb-internal-warning" role="alert">
                    企业内部版，未进行 Windows/macOS
                    发行签名；仅在公司授权设备安装。系统可能要求你确认来源。
                  </p>
                )}
              </div>
            ) : (
              <div className="wb-inline-recovery">
                <span>{downloadError ?? "该平台安装包暂不可用"}</span>
                <button type="button" onClick={() => void loadManifest()}>
                  重新获取
                </button>
              </div>
            )}
          </div>
        </li>

        <li className="wb-guide-step">
          <div className="wb-step-number">2</div>
          <div className="wb-step-body">
            <h3>确认连接器路径并生成个人配置</h3>
            <fieldset className="wb-path-options" disabled={busy}>
              <legend>连接器位置</legend>
              <label>
                <input
                  type="radio"
                  name="workbuddy-path-mode"
                  checked={pathMode === "default"}
                  onChange={() => {
                    setPathMode("default");
                    setConfirmRegeneration(false);
                  }}
                />
                使用默认安装位置
              </label>
              <label>
                <input
                  type="radio"
                  name="workbuddy-path-mode"
                  checked={pathMode === "custom"}
                  onChange={() => {
                    setPathMode("custom");
                    setConfirmRegeneration(false);
                  }}
                />
                使用自定义连接器路径
              </label>
            </fieldset>
            {pathMode === "custom" && (
              <label className="wb-custom-path">
                连接器可执行文件完整路径
                <input
                  value={customPath}
                  onChange={(event) => {
                    setCustomPath(event.target.value);
                    setConfirmRegeneration(false);
                  }}
                  placeholder={DEFAULT_COMMANDS[platform]}
                  aria-invalid={Boolean(customPathError)}
                />
              </label>
            )}
            {customPathError && (
              <p className="wb-field-error" role="alert">
                {customPathError}
              </p>
            )}
            <p>
              KAP 只把你本次提交的路径写入配置文本，不会浏览、上传、探测、记录或远程读取你的电脑。
              如果安装后手动移动了应用，请重新安装/修复安装，或在此更新为实际路径。
            </p>
            <div className="wb-command-preview">
              <strong>将生成 {platform === "windows" ? "Windows" : "macOS"} 配置</strong>
              <code>{selectedCommand || "请先填写有效路径"}</code>
            </div>
            {oneTime && (oneTime.platform !== platform || oneTime.command !== selectedCommand) && (
              <p className="wb-warn">
                当前显示的一次性配置仍使用生成时的{" "}
                {oneTime.platform === "windows" ? "Windows" : "macOS"}{" "}
                路径。当前选择只有在你确认“重新生成配置”后才会生效。
              </p>
            )}
            <div className="wb-actions">
              <button
                type="button"
                onClick={onGenerate}
                disabled={busy || loadingStatus || !artifact || Boolean(customPathError)}
              >
                {enabled || oneTime ? "重新生成配置" : "生成个人配置"}
              </button>
            </div>
            {confirmRegeneration && (
              <div className="wb-regenerate-confirm" role="alert">
                <p>重新生成会立即使旧 token 和旧配置失效。确认继续吗？</p>
                <div className="wb-actions">
                  <button type="button" onClick={() => void performGenerate()} disabled={busy}>
                    确认重新生成配置
                  </button>
                  <button type="button" onClick={() => setConfirmRegeneration(false)}>
                    取消
                  </button>
                </div>
              </div>
            )}
            {oneTime && (
              <div className="wb-onetime" role="region" aria-label="WorkBuddy 配置（仅显示一次）">
                <p className="wb-warn">
                  此配置含仅显示一次的个人凭证，请立即配置；不要转发或保存到共享文档。
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
            <h3>在 WorkBuddy v5.3.5 配置 MCP</h3>
            <p>以下入口已验证于 WorkBuddy v5.3.5：</p>
            <ol className="wb-client-steps">
              <li>
                打开 <strong>专家·技能·连接器</strong>，或切换到顶部 <strong>连接器</strong>。
              </li>
              <li>
                点击右上 <strong>自定义连接器</strong>。
              </li>
              <li>
                在“我的 MCP”弹窗点击右上 <strong>配置 MCP</strong>。
              </li>
              <li>
                在 MCP JSON 配置编辑器中，只替换或合并 <code>mcpServers.kap</code>{" "}
                节点并保存。请保留其他已有 MCP 节点，不要用整份配置覆盖它们。
              </li>
              <li>
                确认 <code>kap</code> 已启用；必要时重启 WorkBuddy。
              </li>
            </ol>
          </div>
        </li>

        <li className="wb-guide-step">
          <div className="wb-step-number">4</div>
          <div className="wb-step-body">
            <h3>验证真实首次连接</h3>
            <p>
              在 WorkBuddy 调用一个只读 KAP 工具，例如“列出我可访问的项目”。只有已鉴权的真实 MCP
              请求成功后，这里才会显示已连接。
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
                  刷新连接状态
                </button>
                <span className="wb-help-text">
                  尚未连接？请确认配置已保存、kap 已启用；必要时重启 WorkBuddy，再调用只读工具。
                </span>
              </div>
            )}
          </div>
        </li>
      </ol>
    </section>
  );
}
