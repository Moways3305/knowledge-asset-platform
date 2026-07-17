import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BadgeCheck,
  BookOpen,
  Database,
  FileClock,
  FolderUp,
  RefreshCw,
  Upload,
} from "lucide-react";
import { ApiError } from "../api/http";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import {
  confirmPersonalAsset,
  createMyKnowledgeBase,
  fetchMyKnowledge,
  fetchMyKnowledgeBase,
  registerPersonalKnowledgeEvidence,
  renameMyKnowledgeBase,
  submitPersonalKnowledge,
  type PersonalKbDTO,
} from "../api/personal";
import ConfirmDialog from "../components/ConfirmDialog";
import ModelAdvancedSettings from "../components/ModelAdvancedSettings";
import { PageHeader, PageSection, ProductPage } from "../components/ProductLayout";
import { useModelSelection } from "../hooks/useModelSelection";
import type { KnowledgeCardVM } from "../types/knowledge";
import { formatBeijingTime } from "../utils/time";
import "./MyKnowledgePage.css";

const SAFE_FALLBACK = "信息待确认";

const typeLabels: Record<string, string> = {
  methodology: "方法论",
  insight: "洞察",
  case: "案例",
  template: "模板",
  deliverable: "交付物",
};

const evidenceCategoryLabels: Record<string, string> = {
  meeting_minutes: "会议纪要",
  wecom_record: "企微记录",
  client_email: "客户邮件",
  acceptance_doc: "验收单",
  delivery_adoption: "交付采纳",
};

const evidenceCategories = Object.keys(evidenceCategoryLabels);

type DialogKind = "create-kb" | "rename-kb" | "confirm" | "submit" | "evidence" | null;
type EvidenceType = "internal_sharing" | "client_validation";
type LoadState = "loading" | "ready" | "error" | "forbidden";

function personalStatus(zone: string) {
  if (zone === "material") return { label: "待本人确认", tone: "draft" };
  if (zone === "asset") return { label: "本人已确认", tone: "confirmed" };
  return { label: SAFE_FALLBACK, tone: "unknown" };
}

function kbStatus(status?: string | null) {
  if (status === "active") return { label: "运行正常", tone: "confirmed" };
  if (status === "init_failed") return { label: "初始化失败", tone: "danger" };
  return { label: SAFE_FALLBACK, tone: "unknown" };
}

function safeActionError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 403) return "当前身份无权执行此操作";
  return fallback;
}

export default function MyKnowledgePage() {
  const [items, setItems] = useState<KnowledgeCardVM[]>([]);
  const [projects, setProjects] = useState<AuthMeVM["projects"]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [kbState, setKbState] = useState<LoadState>("loading");
  const [kb, setKb] = useState<PersonalKbDTO | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialogKind, setDialogKind] = useState<DialogKind>(null);
  const [activeItem, setActiveItem] = useState<KnowledgeCardVM | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [kbName, setKbName] = useState("");
  const [targetProject, setTargetProject] = useState("");
  const [evidenceType, setEvidenceType] = useState<EvidenceType>("internal_sharing");
  const [evidenceCategory, setEvidenceCategory] = useState(evidenceCategories[0]);
  const [evidenceDescription, setEvidenceDescription] = useState("");
  const requestRef = useRef(0);
  const models = useModelSelection();

  const load = useCallback(async () => {
    const request = ++requestRef.current;
    setLoadState("loading");
    try {
      const [knowledge, me] = await Promise.all([
        fetchMyKnowledge(),
        fetchAuthMe().catch(() => null),
      ]);
      if (request !== requestRef.current) return;
      setItems(knowledge);
      setProjects(me?.projects ?? []);
      setLoadState("ready");
    } catch (error) {
      if (request !== requestRef.current) return;
      setItems([]);
      setLoadState(error instanceof ApiError && error.status === 403 ? "forbidden" : "error");
    }
  }, []);

  const loadKb = useCallback(async () => {
    try {
      const data = await fetchMyKnowledgeBase();
      setKb(data);
      setKbState("ready");
    } catch (error) {
      setKb(null);
      setKbState(error instanceof ApiError && error.status === 403 ? "forbidden" : "error");
    }
  }, []);

  useEffect(() => {
    void load();
    void loadKb();
    return () => {
      requestRef.current += 1;
    };
  }, [load, loadKb]);

  const stats = useMemo(() => {
    const drafts = items.filter((item) => item.zone === "material").length;
    const confirmed = items.filter((item) => item.zone === "asset").length;
    return { total: items.length, drafts, confirmed };
  }, [items]);

  const closeDialog = useCallback(() => {
    if (actionBusy) return;
    setDialogKind(null);
    setActiveItem(null);
    setActionError(null);
  }, [actionBusy]);

  const openItemDialog = (
    kind: Exclude<DialogKind, "create-kb" | "rename-kb" | null>,
    item: KnowledgeCardVM,
  ) => {
    setActiveItem(item);
    setDialogKind(kind);
    setTargetProject(projects[0]?.projectId ?? "");
    setEvidenceType("internal_sharing");
    setEvidenceCategory(evidenceCategories[0]);
    setEvidenceDescription("");
    setActionError(null);
  };

  const createKb = async (includeModels: boolean) => {
    if (includeModels && models.blockSubmit) {
      setActionError("默认模型尚未配置，请联系管理员完成配置");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      const data = await createMyKnowledgeBase({
        displayName: kbName.trim() || undefined,
        embeddingModelRef: includeModels ? models.embeddingRef || undefined : undefined,
        rerankModelRef: includeModels ? models.rerankRef || undefined : undefined,
      });
      setKb(data);
      setKbState("ready");
      setDialogKind(null);
      setKbName("");
      setNotice(includeModels ? "个人知识库已创建" : "已重新发起初始化");
    } catch (error) {
      setActionError(
        safeActionError(error, includeModels ? "创建失败，请稍后重试" : "重试失败，请稍后再试"),
      );
    } finally {
      setActionBusy(false);
    }
  };

  const renameKb = async () => {
    if (!kbName.trim()) {
      setActionError("请输入知识库名称");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      const data = await renameMyKnowledgeBase(kbName.trim());
      setKb(data);
      setDialogKind(null);
      setNotice(data.weknora_sync_failed ? "名称已保存，检索服务同步稍后重试" : "知识库名称已更新");
    } catch (error) {
      setActionError(safeActionError(error, "改名失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const confirmItem = async () => {
    if (!activeItem) return;
    setActionBusy(true);
    setActionError(null);
    try {
      await confirmPersonalAsset(activeItem.id);
      setDialogKind(null);
      setActiveItem(null);
      setNotice("已确认为个人知识资产");
      await load();
    } catch (error) {
      setActionError(safeActionError(error, "确认失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const submitItem = async () => {
    if (!activeItem || !targetProject) {
      setActionError("请选择目标项目");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      await submitPersonalKnowledge(activeItem.id, { target_project_id: targetProject });
      setDialogKind(null);
      setActiveItem(null);
      setNotice("已提交，等待项目经理确认");
    } catch (error) {
      setActionError(safeActionError(error, "提交失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const registerEvidence = async () => {
    if (!activeItem || !targetProject) {
      setActionError("请选择目标项目");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      await registerPersonalKnowledgeEvidence(activeItem.id, {
        target_project_id: targetProject,
        evidence_type: evidenceType,
        evidence_category: evidenceCategory,
        description: evidenceDescription.trim() || undefined,
      });
      setDialogKind(null);
      setActiveItem(null);
      setNotice("候选证据已登记，等待项目经理审核");
    } catch (error) {
      setActionError(safeActionError(error, "登记失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const retryKb = async () => createKb(false);
  const forbidden = loadState === "forbidden";
  const hasProjects = projects.length > 0;

  return (
    <ProductPage className="mk82-page">
      <PageHeader
        title="我的个人知识"
        description="整理个人资料，并将确认后的知识提交到项目。"
        actions={
          <>
            <Link className="btn-small-primary mk82-header-action" to="/upload">
              <Upload size={16} aria-hidden="true" />
              上传资料
            </Link>
            <button
              className="btn-small mk82-header-action"
              onClick={() => {
                setNotice(null);
                void load();
              }}
              disabled={loadState === "loading"}
            >
              <RefreshCw size={16} aria-hidden="true" />
              刷新
            </button>
          </>
        }
      />

      {!forbidden && kbState === "ready" && kb?.exists && (
        <div className="mk82-kb-strip" aria-label="个人知识库状态">
          <Database size={18} aria-hidden="true" />
          <div>
            <span className="mk82-kb-label">个人知识库</span>
            <strong>{kb.display_name || "我的知识库"}</strong>
          </div>
          <span className={`mk82-status mk82-status-${kbStatus(kb.status).tone}`}>
            {kbStatus(kb.status).label}
          </span>
          <div className="mk82-kb-actions">
            {kb.status === "init_failed" && (
              <button
                className="btn-small-primary"
                onClick={() => void retryKb()}
                disabled={actionBusy}
              >
                {actionBusy ? "重试中…" : "重新初始化"}
              </button>
            )}
            <button
              className="btn-small"
              onClick={() => {
                setKbName(kb.display_name ?? "");
                setActionError(null);
                setDialogKind("rename-kb");
              }}
            >
              修改名称
            </button>
          </div>
        </div>
      )}

      {!forbidden && kbState === "ready" && kb && !kb.exists && (
        <div className="mk82-kb-empty">
          <Database size={20} aria-hidden="true" />
          <div>
            <strong>尚未创建个人知识库</strong>
            <span>创建后即可集中管理个人资料。</span>
          </div>
          <button
            className="btn-small-primary"
            onClick={() => {
              setKbName("");
              setActionError(null);
              setDialogKind("create-kb");
            }}
          >
            创建知识库
          </button>
        </div>
      )}

      {!forbidden && kbState === "error" && (
        <div className="mk82-inline-alert" role="alert">
          知识库状态暂时无法加载
          <button className="btn-small" onClick={() => void loadKb()}>
            重新加载
          </button>
        </div>
      )}

      {!forbidden && (
        <div className="mk82-stats" aria-label="个人知识统计">
          <article>
            <BookOpen aria-hidden="true" />
            <div>
              <span>资料总数</span>
              <strong>{stats.total}</strong>
            </div>
          </article>
          <article>
            <FileClock aria-hidden="true" />
            <div>
              <span>待本人确认</span>
              <strong>{stats.drafts}</strong>
            </div>
          </article>
          <article>
            <BadgeCheck aria-hidden="true" />
            <div>
              <span>本人已确认</span>
              <strong>{stats.confirmed}</strong>
            </div>
          </article>
        </div>
      )}

      {notice && (
        <div className="mk82-notice" role="status">
          {notice}
        </div>
      )}

      <PageSection
        className="mk82-library"
        title="个人资料"
        actions={<span className="mk82-count">共 {stats.total} 条</span>}
      >
        {forbidden ? (
          <div className="mk82-state">
            <strong>当前身份无法使用个人知识</strong>
          </div>
        ) : loadState === "loading" ? (
          <div className="mk82-state">
            <strong>正在加载个人资料…</strong>
          </div>
        ) : loadState === "error" ? (
          <div className="mk82-state">
            <strong>个人资料暂时无法加载</strong>
            <span>请稍后重试。</span>
            <button className="btn-small" onClick={() => void load()}>
              重新加载
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="mk82-state mk82-state-empty">
            <FolderUp aria-hidden="true" />
            <strong>还没有个人资料</strong>
            <span>上传资料后，可在这里完成本人确认与项目提交。</span>
            <Link className="btn-small-primary" to="/upload">
              上传第一份资料
            </Link>
          </div>
        ) : (
          <div className="mk82-table-wrap">
            <table className="mk82-table">
              <thead>
                <tr>
                  <th>资料名称</th>
                  <th>类型</th>
                  <th>更新时间</th>
                  <th>个人状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const status = personalStatus(item.zone);
                  return (
                    <tr key={item.id}>
                      <td>
                        <Link
                          className="mk82-title-link"
                          to={`/knowledge/${encodeURIComponent(item.id)}`}
                        >
                          {item.title}
                        </Link>
                      </td>
                      <td>
                        <span className="mk82-type">
                          {typeLabels[item.assetType] ?? SAFE_FALLBACK}
                        </span>
                      </td>
                      <td>
                        <time>{formatBeijingTime(item.updatedAt)}</time>
                      </td>
                      <td>
                        <span className={`mk82-status mk82-status-${status.tone}`}>
                          {status.label}
                        </span>
                      </td>
                      <td>
                        <div className="mk82-row-actions">
                          {item.zone === "material" && (
                            <button
                              className="btn-small-primary"
                              onClick={() => openItemDialog("confirm", item)}
                            >
                              本人确认
                            </button>
                          )}
                          {item.zone === "asset" && (
                            <button
                              className="btn-small-primary"
                              disabled={!hasProjects}
                              title={!hasProjects ? "暂无可提交的项目" : undefined}
                              onClick={() => openItemDialog("submit", item)}
                            >
                              提交项目
                            </button>
                          )}
                          <button
                            className="btn-small"
                            disabled={!hasProjects}
                            title={!hasProjects ? "暂无可登记的项目" : undefined}
                            onClick={() => openItemDialog("evidence", item)}
                          >
                            登记证据
                          </button>
                          {!hasProjects && <span className="mk82-action-hint">暂无可用项目</span>}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </PageSection>

      <ConfirmDialog
        open={dialogKind === "create-kb"}
        title="创建个人知识库"
        description="可使用推荐配置直接创建，也可在高级设置中选择可用模型。"
        confirmText="创建"
        busy={actionBusy}
        busyText="创建中…"
        error={actionError}
        onCancel={closeDialog}
        onConfirm={() => void createKb(true)}
      >
        <label className="mk82-field">
          <span>知识库名称（可选）</span>
          <input
            value={kbName}
            maxLength={100}
            placeholder="我的知识库"
            onChange={(event) => setKbName(event.target.value)}
          />
        </label>
        <ModelAdvancedSettings models={models} />
      </ConfirmDialog>

      <ConfirmDialog
        open={dialogKind === "rename-kb"}
        title="修改知识库名称"
        confirmText="保存"
        busy={actionBusy}
        busyText="保存中…"
        error={actionError}
        onCancel={closeDialog}
        onConfirm={() => void renameKb()}
      >
        <label className="mk82-field">
          <span>知识库名称</span>
          <input
            value={kbName}
            maxLength={100}
            onChange={(event) => setKbName(event.target.value)}
          />
        </label>
      </ConfirmDialog>

      <ConfirmDialog
        open={dialogKind === "confirm"}
        title="确认为个人知识资产"
        description={
          activeItem
            ? `确认“${activeItem.title}”已整理完成？此操作不会将资料公开或加入项目。`
            : undefined
        }
        confirmText="确认资产"
        busy={actionBusy}
        error={actionError}
        onCancel={closeDialog}
        onConfirm={() => void confirmItem()}
      />

      <ConfirmDialog
        open={dialogKind === "submit"}
        title="提交到项目"
        description="提交后将等待项目经理确认，通过前不会进入项目知识库。"
        confirmText="提交"
        busy={actionBusy}
        error={actionError}
        onCancel={closeDialog}
        onConfirm={() => void submitItem()}
      >
        <label className="mk82-field">
          <span>目标项目</span>
          <select value={targetProject} onChange={(event) => setTargetProject(event.target.value)}>
            {projects.map((project) => (
              <option key={project.projectId} value={project.projectId}>
                {project.projectName}
              </option>
            ))}
          </select>
        </label>
      </ConfirmDialog>

      <ConfirmDialog
        open={dialogKind === "evidence"}
        title="登记候选证据"
        description="这里只登记证据线索，不代表分享、客户验证或项目采纳已经成立。"
        confirmText="登记候选"
        busy={actionBusy}
        error={actionError}
        onCancel={closeDialog}
        onConfirm={() => void registerEvidence()}
      >
        <div className="mk82-dialog-grid">
          <label className="mk82-field">
            <span>目标项目</span>
            <select
              value={targetProject}
              onChange={(event) => setTargetProject(event.target.value)}
            >
              {projects.map((project) => (
                <option key={project.projectId} value={project.projectId}>
                  {project.projectName}
                </option>
              ))}
            </select>
          </label>
          <label className="mk82-field">
            <span>证据类型</span>
            <select
              value={evidenceType}
              onChange={(event) => setEvidenceType(event.target.value as EvidenceType)}
            >
              <option value="internal_sharing">内部分享候选</option>
              <option value="client_validation">客户验证候选</option>
            </select>
          </label>
          <label className="mk82-field">
            <span>证据类别</span>
            <select
              value={evidenceCategory}
              onChange={(event) => setEvidenceCategory(event.target.value)}
            >
              {evidenceCategories.map((category) => (
                <option key={category} value={category}>
                  {evidenceCategoryLabels[category]}
                </option>
              ))}
            </select>
          </label>
          <label className="mk82-field mk82-field-wide">
            <span>补充说明（可选）</span>
            <textarea
              value={evidenceDescription}
              maxLength={500}
              onChange={(event) => setEvidenceDescription(event.target.value)}
            />
          </label>
        </div>
      </ConfirmDialog>
    </ProductPage>
  );
}
