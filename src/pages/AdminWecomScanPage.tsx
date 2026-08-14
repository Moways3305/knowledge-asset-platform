import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FolderSync, RefreshCw, ShieldCheck } from "lucide-react";
import {
  fetchWecomScanConfigs,
  fetchWecomScanOwnerOptions,
  fetchWecomScanProjectOptions,
  fetchWecomScanRecords,
  triggerWecomScan,
  updateWecomScanConfig,
} from "../api/admin";
import { ApiError } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import type {
  WecomOwnerOptionDTO,
  WecomProjectOptionDTO,
  WecomScanConfigDTO,
  WecomScanRecordDTO,
} from "../types/wecom";
import { formatBeijingTime } from "../utils/time";
import WecomScanConfigForm from "./wecomScan/WecomScanConfigForm";
import WecomScanConfigList from "./wecomScan/WecomScanConfigList";
import { scanStatusCls, scanStatusLabel } from "./wecomScan/labels";
import "./AdminWecomScanPage.css";

function safeRequestMessage(error: unknown, fallback: string) {
  if (
    error instanceof ApiError &&
    error.status === 403 &&
    error.deniedReason !== "wecom_drive_permission_denied"
  )
    return "当前身份没有该项目的微盘扫描权限。";
  if (error instanceof ApiError && error.deniedReason === "wecom_drive_permission_denied")
    return "企业微信应用未获得微盘权限，请管理员启用“协作-微盘-API”后重试。";
  if (
    error instanceof ApiError &&
    (error.deniedReason === "wecom_token_rejected" || error.deniedReason === "wecom_token_missing")
  )
    return "企业微信应用凭证无效，请管理员检查应用凭证后重试。";
  if (error instanceof ApiError && error.deniedReason?.startsWith("wecom_api_"))
    return "企业微信拒绝读取微盘。请检查应用微盘权限或目录授权后重试。";
  if (error instanceof ApiError && error.deniedReason === "wecom_drive_network_unavailable")
    return "企业微信微盘暂时不可用，请稍后重试。";
  if (error instanceof ApiError && error.status === 503)
    return "企业微信微盘尚未配置或暂不可用，请联系系统管理员检查连接。";
  return fallback;
}

function safeRecordError(record: WecomScanRecordDTO) {
  if (!record.error_type) return null;
  const type = record.error_type.toLowerCase();
  if (type.includes("owner"))
    return { category: "业务归属失效", action: "重新选择有效的业务归属人并保存配置。" };
  if (type.includes("token") || type.includes("auth") || type.includes("credential"))
    return { category: "企业微信授权失效", action: "请系统管理员检查企业微信授权后重试。" };
  if (type.includes("timeout") || type.includes("rate") || type.includes("unavailable"))
    return { category: "企业微信服务暂不可用", action: "稍后重新扫描；持续失败时请检查服务连接。" };
  return { category: "扫描未完成", action: "请检查扫描配置后重试。" };
}

export default function AdminWecomScanPage() {
  const { capabilities } = useAuth();
  const [accessForbidden, setAccessForbidden] = useState(false);
  const canEdit =
    (capabilities.isAdmin || capabilities.isGovernance || capabilities.isProjectManager) &&
    !accessForbidden;
  const [configs, setConfigs] = useState<WecomScanConfigDTO[]>([]);
  const [latest, setLatest] = useState<Record<string, WecomScanRecordDTO | null>>({});
  const [loading, setLoading] = useState(true);
  const [configError, setConfigError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [records, setRecords] = useState<WecomScanRecordDTO[]>([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [projectOptions, setProjectOptions] = useState<WecomProjectOptionDTO[]>([]);
  const [ownerOptions, setOwnerOptions] = useState<WecomOwnerOptionDTO[]>([]);
  const [optionsError, setOptionsError] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [editingConfig, setEditingConfig] = useState<WecomScanConfigDTO | null>(null);
  const recordsRequestRef = useRef(0);
  const enterReadOnly = useCallback(() => {
    setAccessForbidden(true);
    setFormOpen(false);
  }, []);

  const loadRecords = useCallback(
    async (configId: string) => {
      const requestId = ++recordsRequestRef.current;
      setRecordsLoading(true);
      setRecordError(null);
      try {
        const response = await fetchWecomScanRecords(configId);
        if (requestId !== recordsRequestRef.current) return;
        setRecords(response.items);
        setLatest((current) => ({ ...current, [configId]: response.items[0] ?? null }));
      } catch (error) {
        if (error instanceof ApiError && error.status === 403) enterReadOnly();
        if (requestId !== recordsRequestRef.current) return;
        setRecords([]);
        setRecordError(safeRequestMessage(error, "扫描记录暂时无法加载，请稍后重试。"));
      } finally {
        if (requestId === recordsRequestRef.current) setRecordsLoading(false);
      }
    },
    [enterReadOnly],
  );

  const loadPage = useCallback(async () => {
    setLoading(true);
    setConfigError(null);
    setAccessForbidden(false);
    try {
      const response = await fetchWecomScanConfigs();
      setConfigs(response.items);
      setSelectedId((current) =>
        current && response.items.some((item) => item.id === current)
          ? current
          : (response.items[0]?.id ?? null),
      );
      const snapshots = await Promise.allSettled(
        response.items.map(
          async (config) =>
            [config.id, (await fetchWecomScanRecords(config.id)).items[0] ?? null] as readonly [
              string,
              WecomScanRecordDTO | null,
            ],
        ),
      );
      if (
        snapshots.some(
          (item) =>
            item.status === "rejected" &&
            item.reason instanceof ApiError &&
            item.reason.status === 403,
        )
      ) {
        enterReadOnly();
      }
      setLatest(
        Object.fromEntries(
          snapshots
            .filter(
              (
                item,
              ): item is PromiseFulfilledResult<readonly [string, WecomScanRecordDTO | null]> =>
                item.status === "fulfilled",
            )
            .map((item) => item.value),
        ),
      );
    } catch (error) {
      setConfigs([]);
      setSelectedId(null);
      if (error instanceof ApiError && error.status === 403) {
        enterReadOnly();
        setConfigError("当前身份没有微盘扫描管理权限，此区域保持只读。");
      } else {
        setConfigError(safeRequestMessage(error, "扫描配置暂时无法加载，请稍后刷新。"));
      }
    } finally {
      setLoading(false);
    }
  }, [enterReadOnly]);

  const loadOptions = useCallback(async () => {
    if (!canEdit) return;
    setOptionsError(false);
    try {
      const [projects, owners] = await Promise.all([
        fetchWecomScanProjectOptions(),
        fetchWecomScanOwnerOptions(),
      ]);
      setProjectOptions(projects.items);
      setOwnerOptions(owners.items);
    } catch (error) {
      setProjectOptions([]);
      setOwnerOptions([]);
      setOptionsError(true);
      if (error instanceof ApiError && error.status === 403) enterReadOnly();
    }
  }, [canEdit, enterReadOnly]);

  useEffect(() => void loadPage(), [loadPage]);
  useEffect(() => void loadOptions(), [loadOptions]);
  useEffect(() => {
    if (selectedId) void loadRecords(selectedId);
    else {
      recordsRequestRef.current += 1;
      setRecords([]);
      setRecordError(null);
      setRecordsLoading(false);
    }
    return () => {
      recordsRequestRef.current += 1;
    };
  }, [selectedId, loadRecords]);

  const selectedConfig = configs.find((item) => item.id === selectedId) ?? null;
  const summary = useMemo(() => {
    const enabled = configs.filter((item) => item.enabled).length;
    const unavailable = configs.filter(
      (item) =>
        item.enabled &&
        (item.scan_space_status !== "ready" || item.manager_access_status !== "ready"),
    ).length;
    const failedRuns = Object.values(latest).filter((item) => (item?.failed_count ?? 0) > 0).length;
    return {
      enabled,
      unavailable,
      failedRuns,
    };
  }, [configs, latest]);
  const prioritizedConfigs = useMemo(
    () =>
      [...configs].sort((left, right) => {
        const issueScore = (config: WecomScanConfigDTO) =>
          Number(
            config.enabled &&
              (config.scan_space_status !== "ready" ||
                config.manager_access_status !== "ready" ||
                (latest[config.id]?.failed_count ?? 0) > 0),
          );
        return issueScore(right) - issueScore(left);
      }),
    [configs, latest],
  );

  const mergeConfig = (saved: WecomScanConfigDTO) => {
    setConfigs((current) => {
      const exists = current.some((item) => item.id === saved.id);
      return exists
        ? current.map((item) => (item.id === saved.id ? saved : item))
        : [saved, ...current];
    });
    setSelectedId(saved.id);
  };

  const handleToggle = async (config: WecomScanConfigDTO) => {
    setBusyId(config.id);
    setNotice(null);
    try {
      mergeConfig(await updateWecomScanConfig(config.id, { enabled: !config.enabled }));
      setNotice({
        tone: "success",
        text: config.enabled ? "扫描配置已停用。" : "扫描配置已启用。",
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) enterReadOnly();
      setNotice({
        tone: "danger",
        text: safeRequestMessage(error, "配置状态更新失败，请稍后重试。"),
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleScan = async (config: WecomScanConfigDTO) => {
    if (!config.enabled) return;
    setBusyId(config.id);
    setNotice(null);
    try {
      const record = await triggerWecomScan(config.id);
      setLatest((current) => ({ ...current, [config.id]: record }));
      setSelectedId(config.id);
      await loadRecords(config.id);
      setConfigs((current) =>
        current.map((item) =>
          item.id === config.id ? { ...item, last_scan_at: record.scan_started_at } : item,
        ),
      );
      setNotice({
        tone: "success",
        text: `扫描已结束：发现 ${record.discovered_count}，新增待确认 ${record.new_count}，重复 ${record.duplicate_count}，失败 ${record.failed_count}。`,
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) enterReadOnly();
      setNotice({
        tone: "danger",
        text: safeRequestMessage(error, "扫描未能完成，请检查配置后重试。"),
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <ProductPage className="ws87-page admin-control-page">
      <PageHeader
        title="微盘扫描"
        status={
          <StatusBadge
            tone={
              summary.unavailable || summary.failedRuns ? "danger" : busyId ? "info" : "success"
            }
            label={
              summary.unavailable || summary.failedRuns
                ? "存在需要处理的配置"
                : busyId
                  ? "扫描处理中"
                  : "连接可用"
            }
          />
        }
        actions={
          <>
            {canEdit && (
              <button
                className="btn-small-primary ws87-icon-button"
                onClick={() => {
                  setEditingConfig(null);
                  setFormOpen(true);
                }}
              >
                <FolderSync size={14} />
                新增扫描配置
              </button>
            )}
            <button
              className="btn-small ws87-icon-button"
              onClick={() => void loadPage()}
              disabled={loading}
            >
              <RefreshCw size={14} />
              {loading ? "刷新中…" : "刷新"}
            </button>
          </>
        }
      />

      {!canEdit && (
        <div className="ws87-message">
          <ShieldCheck size={15} />
          当前身份为只读模式，可查看扫描配置与运行记录。
        </div>
      )}
      {notice && (
        <div
          className={`ws87-message is-${notice.tone}`}
          role={notice.tone === "danger" ? "alert" : undefined}
        >
          {notice.text}
        </div>
      )}

      <div className="ws87-console">
        <main className="ws87-main-workspace">
          <section className="ws87-config-panel admin-workspace-panel">
            <div className="ws87-panel-heading">
              <h3>{summary.unavailable + summary.failedRuns ? "配置处置队列" : "扫描配置"}</h3>
              <span className={summary.unavailable + summary.failedRuns ? "is-danger" : ""}>
                {summary.unavailable + summary.failedRuns
                  ? `${summary.unavailable + summary.failedRuns} 项异常已置顶`
                  : "当前连接均可用"}
              </span>
            </div>
            <WecomScanConfigList
              configs={prioritizedConfigs}
              latest={latest}
              loading={loading}
              error={configError}
              busyId={busyId}
              selectedId={selectedId}
              canEdit={canEdit}
              onReload={() => void loadPage()}
              onSelect={setSelectedId}
              onEdit={(config) => {
                setEditingConfig(config);
                setFormOpen(true);
              }}
              onToggle={(config) => void handleToggle(config)}
              onScan={(config) => void handleScan(config)}
            />
          </section>

          <WecomScanConfigForm
            open={formOpen && canEdit}
            editingConfig={editingConfig}
            projectOptions={projectOptions}
            ownerOptions={ownerOptions}
            optionsError={optionsError}
            onForbidden={enterReadOnly}
            onClose={() => setFormOpen(false)}
            onSaved={(saved, text) => {
              mergeConfig(saved);
              setNotice({ tone: "success", text });
            }}
          />

          {selectedConfig && (
            <section className="ws87-record-panel" aria-label="最近扫描记录">
              <div className="ws87-panel-heading">
                <h3>{selectedConfig.name || "未命名配置"} · 最近扫描记录</h3>
              </div>
              {recordError ? (
                <div className="ws87-empty is-danger">{recordError}</div>
              ) : recordsLoading ? (
                <div className="ws87-empty">正在读取扫描记录…</div>
              ) : records.length === 0 ? (
                <div className="ws87-empty">
                  <strong>尚未运行</strong>
                  {selectedConfig.enabled && canEdit && <span>可从配置列表发起扫描。</span>}
                </div>
              ) : (
                <div className="ws87-records">
                  <table className="ws87-record-table">
                    <thead>
                      <tr>
                        <th>开始时间</th>
                        <th>完成时间</th>
                        <th>状态</th>
                        <th>发现</th>
                        <th>新增</th>
                        <th>重复</th>
                        <th>失败</th>
                        <th>处理提示</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((record, index) => {
                        const safeError = safeRecordError(record);
                        return (
                          <tr key={`${record.scan_started_at}-${index}`}>
                            <td data-label="开始时间">
                              {formatBeijingTime(record.scan_started_at)}
                            </td>
                            <td data-label="完成时间">
                              {formatBeijingTime(record.scan_completed_at)}
                            </td>
                            <td data-label="状态">
                              <span
                                className={`ws87-pill ${scanStatusCls[record.scan_status] ?? "ws-result-empty"}`}
                              >
                                {scanStatusLabel[record.scan_status] ?? "未知"}
                              </span>
                            </td>
                            <td data-label="发现">{record.discovered_count}</td>
                            <td data-label="新增">{record.new_count}</td>
                            <td data-label="重复">{record.duplicate_count}</td>
                            <td data-label="失败">{record.failed_count}</td>
                            <td data-label="处理提示" className="ws87-record-guidance">
                              {safeError ? (
                                <>
                                  <strong>{safeError.category}</strong>
                                  <span>{safeError.action}</span>
                                </>
                              ) : (
                                "—"
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}
        </main>
      </div>
    </ProductPage>
  );
}
