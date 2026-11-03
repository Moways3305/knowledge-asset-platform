import { Navigate } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";
import { LibraryBig, RefreshCw, Trash2 } from "lucide-react";
import { ApiError } from "../api/http";
import {
  createCompanyKnowledgeBase,
  deleteCompanyKnowledgeBase,
  fetchCompanyKnowledgeBase,
} from "../api/admin";
import type { CompanyKnowledgeBaseDTO } from "../types/people";
import { formatBeijingTime } from "../utils/time";
import { useAuth } from "../auth/AuthContext";
import ConfirmDialog from "../components/ConfirmDialog";
import "./AdminCompanyKbPage.css";

const statusLabel: Record<string, string> = {
  active: "正常",
  inactive: "已停用",
  initializing: "配置中",
  init_failed: "初始化失败",
  pending: "待配置",
  disabled: "已停用",
};

const fmtTime = (iso: string | null): string => formatBeijingTime(iso);

const describeError = (e: unknown, fallback: string): string =>
  e instanceof ApiError && e.status === 403 ? "当前身份没有执行此操作的权限。" : fallback;

export default function AdminCompanyKbPage() {
  return <Navigate to="/company-governance?settings=knowledge-base" replace />;
}

export function CompanyKnowledgeBaseSettings({
  onBusyChange,
}: {
  onBusyChange?: (busy: boolean) => void;
}) {
  const { capabilities } = useAuth();
  const canCreate = capabilities.isBoss || capabilities.isConsultingDirector;
  const canDelete = capabilities.isBoss;

  const [companyKb, setCompanyKb] = useState<CompanyKnowledgeBaseDTO | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);
  const [deleteConfirmName, setDeleteConfirmName] = useState("");
  const [createConfirmOpen, setCreateConfirmOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  useEffect(() => {
    onBusyChange?.(actionBusy || createConfirmOpen || deleteConfirmOpen);
  }, [actionBusy, createConfirmOpen, deleteConfirmOpen, onBusyChange]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCompanyKb(await fetchCompanyKnowledgeBase());
    } catch (e) {
      setCompanyKb(null);
      setError(describeError(e, "公司知识库状态加载失败，请稍后重试"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    if (!canCreate) return;
    setCreateConfirmOpen(true);
  };

  const confirmCreate = async () => {
    setCreateConfirmOpen(false);
    setActionBusy(true);
    setActionError(null);
    setActionNote(null);
    try {
      setCompanyKb(await createCompanyKnowledgeBase());
      setActionNote("公司知识库状态已更新");
    } catch (e) {
      setActionError(describeError(e, "公司知识库创建失败"));
    } finally {
      setActionBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!canDelete || !companyKb) return;
    const expected = companyKb.display_name ?? "公司知识库";
    if (deleteConfirmName.trim() !== expected) {
      setActionError(`请输入“${expected}”以确认删除`);
      return;
    }
    setDeleteConfirmOpen(true);
  };

  const confirmDelete = async () => {
    setActionNote(null);
    setDeleteConfirmOpen(false);
    setActionBusy(true);
    setActionError(null);
    try {
      await deleteCompanyKnowledgeBase();
      setActionNote("公司知识库已删除");
      setDeleteConfirmName("");
      await load();
    } catch (e) {
      setActionError(describeError(e, "删除失败，请检查库内是否仍有资产后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <div className="company-kb-settings">
      <div className="company-kb-settings-toolbar">
        <h3 id="company-kb-heading">公司知识库状态</h3>
        <button
          type="button"
          className="btn-small"
          onClick={() => void load()}
          disabled={loading || actionBusy}
        >
          <RefreshCw size={13} aria-hidden="true" /> {loading ? "加载中…" : "刷新状态"}
        </button>
      </div>

      <div className="company-kb-workspace">
        <div className="company-kb-content">
          {error ? (
            <div className="ig-empty-state">
              <div className="gp-empty-visual is-error" aria-hidden="true">
                <LibraryBig size={22} />
                <span />
              </div>
              <div className="ig-empty-title">无法加载</div>
              <p className="ig-empty-desc">{error}</p>
              <button type="button" className="btn-small" onClick={() => void load()}>
                重试
              </button>
            </div>
          ) : loading ? (
            <div className="ig-empty-state">
              <div className="ig-empty-title">加载中…</div>
            </div>
          ) : (
            <section className="company-kb-status-panel" aria-labelledby="company-kb-heading">
              {companyKb?.exists ? (
                <p className="pp-toolbar-hint">
                  {companyKb.availability_summary ?? "暂无公司知识库信息"}
                </p>
              ) : (
                <div className="ckb-empty-card">
                  <span className="ckb-empty-icon" aria-hidden="true">
                    <LibraryBig size={22} />
                  </span>
                  <div>
                    <strong>尚未创建</strong>
                    <p>创建后可统一承载公司范围知识；初始化完成前不会用于公司知识入库。</p>
                  </div>
                  {canCreate && (
                    <button
                      type="button"
                      className="btn-small btn-small-primary"
                      disabled={actionBusy}
                      onClick={() => void handleCreate()}
                    >
                      {actionBusy ? "处理中…" : "创建公司知识库"}
                    </button>
                  )}
                </div>
              )}

              {companyKb?.exists && (
                <dl className="company-kb-facts">
                  <div>
                    <dt>知识库名称</dt>
                    <dd>{companyKb.display_name ?? "公司知识库"}</dd>
                  </div>
                  <div>
                    <dt>当前可用性</dt>
                    <dd>{companyKb.available ? "可用" : "暂不可用"}</dd>
                  </div>
                  {companyKb.status && (
                    <div>
                      <dt>初始化状态</dt>
                      <dd>{statusLabel[companyKb.status] ?? companyKb.status}</dd>
                    </div>
                  )}
                  <div>
                    <dt>创建时间</dt>
                    <dd>{fmtTime(companyKb.created_at)}</dd>
                  </div>
                </dl>
              )}

              {actionError && (
                <div
                  className="up-submit-notice"
                  role="alert"
                  style={{ color: "var(--color-danger-fg, #b00)", marginTop: 10 }}
                >
                  {actionError}
                </div>
              )}
              {actionNote && (
                <div
                  className="up-submit-notice"
                  role="status"
                  style={{ color: "var(--color-success-fg, #176)", marginTop: 10 }}
                >
                  {actionNote}
                </div>
              )}

              {companyKb?.exists && (
                <div className="ckb-actions">
                  {canCreate && companyKb?.exists && !companyKb.available && (
                    <button
                      type="button"
                      className="btn-small btn-small-primary"
                      disabled={actionBusy}
                      onClick={() => void handleCreate()}
                    >
                      {actionBusy ? "处理中…" : "重试初始化"}
                    </button>
                  )}

                  {canDelete && companyKb?.exists && (
                    <details className="ckb-danger-zone">
                      <summary>危险操作</summary>
                      <div className="ckb-delete-form">
                        <label>
                          <span>输入“{companyKb.display_name ?? "公司知识库"}”以确认删除</span>
                          <input
                            type="text"
                            value={deleteConfirmName}
                            disabled={actionBusy}
                            onChange={(event) => setDeleteConfirmName(event.target.value)}
                            placeholder={companyKb.display_name ?? "公司知识库"}
                            autoComplete="off"
                          />
                        </label>
                        <button
                          type="button"
                          className="btn-small pp-remove-btn ckb-delete-btn"
                          disabled={
                            actionBusy ||
                            deleteConfirmName.trim() !== (companyKb.display_name ?? "公司知识库")
                          }
                          onClick={() => void handleDelete()}
                        >
                          <Trash2 size={13} /> {actionBusy ? "删除中…" : "删除公司知识库"}
                        </button>
                      </div>
                    </details>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      </div>
      <ConfirmDialog
        portal
        open={createConfirmOpen}
        title={companyKb?.exists ? "确认重试初始化公司知识库？" : "确认创建公司知识库？"}
        description={
          companyKb?.exists
            ? "重试将重新触发公司知识库初始化流程。"
            : "创建后即可统一承载公司范围知识；初始化完成前不会用于公司知识入库。"
        }
        confirmText={companyKb?.exists ? "重试初始化" : "创建公司知识库"}
        busyText="处理中…"
        busy={actionBusy}
        error={actionError}
        errorDescription={actionError}
        onConfirm={() => void confirmCreate()}
        onCancel={() => setCreateConfirmOpen(false)}
      />
      <ConfirmDialog
        portal
        open={deleteConfirmOpen}
        title="确认删除公司知识库？"
        description="删除后不可恢复，且需先移除库内全部资产。"
        confirmText="删除公司知识库"
        busyText="删除中…"
        busy={actionBusy}
        danger
        error={actionError}
        errorDescription={actionError}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteConfirmOpen(false)}
      />
    </div>
  );
}
