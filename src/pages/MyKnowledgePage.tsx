import { useState, useMemo, useEffect, useCallback } from "react";
import { ApiError } from "../api/http";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import {
  fetchMyKnowledge,
  confirmPersonalAsset,
  submitPersonalKnowledge,
  registerPersonalKnowledgeEvidence,
  fetchMyKnowledgeBase,
  createMyKnowledgeBase,
  renameMyKnowledgeBase,
  type PersonalKbDTO,
} from "../api/personal";
import type { KnowledgeCardVM } from "../types/knowledge";
import WorkbuddyAccessCard from "../components/WorkbuddyAccessCard";
import ModelAdvancedSettings from "../components/ModelAdvancedSettings";
import { useModelSelection } from "../hooks/useModelSelection";

const kbStatusLabel: Record<string, string> = {
  active: "正常",
  init_failed: "初始化失败",
};

const indexStatusLabel: Record<string, string> = {
  indexed: "已索引",
  index_failed: "索引失败",
  not_indexed: "未索引",
  indexing: "索引中",
  skipped: "已跳过",
};

const typeLabel: Record<string, string> = {
  methodology: "方法论",
  insight: "洞察",
  case: "案例",
  template: "模板",
  deliverable: "交付物",
};

const evidenceCategoryLabel: Record<string, string> = {
  meeting_minutes: "会议纪要",
  wecom_record: "企微记录",
  client_email: "客户邮件",
  acceptance_doc: "验收单",
  delivery_adoption: "交付采纳",
};
const EVIDENCE_CATEGORIES = Object.keys(evidenceCategoryLabel);

// 个人知识展示状态：material=私密草稿 / asset=本人已确认资产。
function zoneStatus(zone: string): { label: string; cls: string } {
  if (zone === "asset") return { label: "本人已确认资产", cls: "mk-vis-asset" };
  return { label: "私密（草稿）", cls: "mk-vis-private" };
}

export default function MyKnowledgePage() {
  const [items, setItems] = useState<KnowledgeCardVM[]>([]);
  const [projects, setProjects] = useState<AuthMeVM["projects"]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);

  // 写动作交互态
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string | null>(null);
  // 候选证据表单
  const [evidenceMode, setEvidenceMode] = useState<"internal_sharing" | "client_validation" | null>(
    null,
  );
  const [targetProject, setTargetProject] = useState("");
  const [evidenceCategory, setEvidenceCategory] = useState(EVIDENCE_CATEGORIES[0]);
  const [evidenceDesc, setEvidenceDesc] = useState("");

  // 个人知识库管理（PBC-29）
  const [kb, setKb] = useState<PersonalKbDTO | null>(null);
  const [kbBusy, setKbBusy] = useState(false);
  const [kbError, setKbError] = useState<string | null>(null);
  const [kbNameDraft, setKbNameDraft] = useState("");
  const [kbEditing, setKbEditing] = useState(false);
  // PBC-38：创建个人知识库时的模型选择（默认平台推荐；缺默认禁用创建）。
  const models = useModelSelection();

  const describeError = (e: unknown, fallback: string) =>
    e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : fallback;

  const loadKb = useCallback(async () => {
    try {
      const data = await fetchMyKnowledgeBase();
      setKb(data);
    } catch (e) {
      // 非业务用户（admin）等 → 隐藏管理卡，不打断知识列表展示。
      if (e instanceof ApiError && e.status === 403) setKb(null);
      else setKb(null);
    }
  }, []);

  // includeModels：首建时随选中的 model_ref；init_failed 重试时省略（沿用 KB 已锁定模型）。
  const doCreateKb = useCallback(
    async (includeModels: boolean) => {
      setKbBusy(true);
      setKbError(null);
      try {
        const data = await createMyKnowledgeBase({
          displayName: kbNameDraft.trim() || undefined,
          embeddingModelRef: includeModels ? models.embeddingRef || undefined : undefined,
          rerankModelRef: includeModels ? models.rerankRef || undefined : undefined,
        });
        setKb(data);
        setKbNameDraft("");
      } catch (e) {
        setKbError(describeError(e, "创建知识库失败"));
      } finally {
        setKbBusy(false);
      }
    },
    [kbNameDraft, models.embeddingRef, models.rerankRef],
  );

  const doRenameKb = useCallback(async () => {
    const name = kbNameDraft.trim();
    if (!name) {
      setKbError("名称不能为空");
      return;
    }
    setKbBusy(true);
    setKbError(null);
    try {
      const data = await renameMyKnowledgeBase(name);
      setKb(data);
      setKbEditing(false);
      if (data.weknora_sync_failed) setKbError("名称已保存，检索服务同步稍后重试");
    } catch (e) {
      setKbError(describeError(e, "改名失败"));
    } finally {
      setKbBusy(false);
    }
  }, [kbNameDraft]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setForbidden(false);
    try {
      const [data, me] = await Promise.all([fetchMyKnowledge(), fetchAuthMe().catch(() => null)]);
      setItems(data);
      setProjects(me?.projects ?? []);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setForbidden(true);
      else setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    void loadKb();
  }, [loadKb]);

  const stats = useMemo(() => {
    const drafts = items.filter((i) => i.zone !== "asset").length;
    const assets = items.filter((i) => i.zone === "asset").length;
    return { total: items.length, drafts, assets };
  }, [items]);

  const selectedItem = selectedId ? (items.find((i) => i.id === selectedId) ?? null) : null;

  // 切换选中条目时重置写动作表单态。
  useEffect(() => {
    setActionError(null);
    setActionNote(null);
    setEvidenceMode(null);
    setTargetProject(projects[0]?.projectId ?? "");
    setEvidenceCategory(EVIDENCE_CATEGORIES[0]);
    setEvidenceDesc("");
  }, [selectedId, projects]);

  const hasProjects = projects.length > 0;

  const doConfirm = useCallback(
    async (assetId: string) => {
      setActionBusy(true);
      setActionError(null);
      setActionNote(null);
      try {
        const r = await confirmPersonalAsset(assetId);
        setActionNote(r.message);
        await load();
      } catch (e) {
        setActionError(describeError(e, "确认资产失败"));
      } finally {
        setActionBusy(false);
      }
    },
    [load],
  );

  const doSubmit = useCallback(
    async (assetId: string) => {
      if (!targetProject) {
        setActionError("请选择目标项目");
        return;
      }
      setActionBusy(true);
      setActionError(null);
      setActionNote(null);
      try {
        const r = await submitPersonalKnowledge(assetId, { target_project_id: targetProject });
        setActionNote(r.message);
      } catch (e) {
        setActionError(describeError(e, "提交项目资料失败"));
      } finally {
        setActionBusy(false);
      }
    },
    [targetProject],
  );

  const doEvidence = useCallback(
    async (assetId: string) => {
      if (!evidenceMode) return;
      if (!targetProject) {
        setActionError("请选择目标项目");
        return;
      }
      setActionBusy(true);
      setActionError(null);
      setActionNote(null);
      try {
        const r = await registerPersonalKnowledgeEvidence(assetId, {
          target_project_id: targetProject,
          evidence_type: evidenceMode,
          evidence_category: evidenceCategory,
          description: evidenceDesc || undefined,
        });
        setActionNote(r.message);
        setEvidenceMode(null);
      } catch (e) {
        setActionError(describeError(e, "登记候选失败"));
      } finally {
        setActionBusy(false);
      }
    },
    [evidenceMode, targetProject, evidenceCategory, evidenceDesc],
  );

  return (
    <div className="mk-page">
      <div className="kl-header">
        <div className="kl-header-text">
          <h2>个人知识管理</h2>
          <p>这里保存你提交和管理的个人知识。需要进入项目库的内容，可提交给项目负责人确认。</p>
        </div>
        <div className="kl-kpis">
          <div className="kl-kpi">
            <div className="kl-kpi-value">{stats.total}</div>
            <div className="kl-kpi-label">知识条目</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value">{stats.drafts}</div>
            <div className="kl-kpi-label">私密草稿</div>
          </div>
          <div className="kl-kpi">
            <div className="kl-kpi-value kl-kpi-success">{stats.assets}</div>
            <div className="kl-kpi-label">本人已确认</div>
          </div>
        </div>
      </div>

      <section className="mk-section">
        <h3>个人知识管理原则</h3>
        <div className="mk-principle-grid">
          <div className="mk-principle-card">
            <div className="mk-principle-icon">🔒</div>
            <div className="mk-principle-text">个人知识默认私密，不参与他人检索</div>
          </div>
          <div className="mk-principle-card">
            <div className="mk-principle-icon">👤</div>
            <div className="mk-principle-text">项目经理和其他顾问无法搜索到你的个人知识</div>
          </div>
          <div className="mk-principle-card">
            <div className="mk-principle-icon">📤</div>
            <div className="mk-principle-text">只有你主动提交，个人知识才进入项目侧</div>
          </div>
          <div className="mk-principle-card">
            <div className="mk-principle-icon">📋</div>
            <div className="mk-principle-text">提交到项目资料区不等于项目资产，资产需验证</div>
          </div>
        </div>
      </section>

      {/* WorkBuddy 自助接入（PBC-36）：仅在职业务用户可见 */}
      <WorkbuddyAccessCard />

      {/* 个人知识库管理（PBC-29）：创建 / 改名 / 状态 */}
      {!forbidden && (
        <section className="mk-section">
          <h3>我的知识库</h3>
          {kbError && (
            <div className="up-submit-notice" style={{ color: "var(--color-danger-fg, #b00)" }}>
              {kbError}
            </div>
          )}
          {kb === null ? (
            <div className="mk-action-note">个人知识库状态加载中…</div>
          ) : !kb.exists ? (
            <div className="mk-kb-card mk-kb-empty">
              <p className="kl-empty-desc">
                你还没有个人知识库，创建后可以上传和管理自己的知识资产。
              </p>
              <div className="mk-vis-controls">
                <input
                  className="up-edit-input"
                  placeholder="知识库名称（可选，默认「我的知识库」）"
                  value={kbNameDraft}
                  maxLength={100}
                  onChange={(e) => setKbNameDraft(e.target.value)}
                />
                <button
                  className="btn-small-primary"
                  disabled={kbBusy || models.blockSubmit}
                  onClick={() => void doCreateKb(true)}
                >
                  {kbBusy ? "创建中…" : "创建我的知识库"}
                </button>
              </div>
              <ModelAdvancedSettings models={models} />
            </div>
          ) : (
            <div className="mk-kb-card">
              <div className="mk-kb-row">
                <span className="mk-detail-label">名称</span>
                {kbEditing ? (
                  <span className="mk-vis-controls">
                    <input
                      className="up-edit-input"
                      value={kbNameDraft}
                      maxLength={100}
                      onChange={(e) => setKbNameDraft(e.target.value)}
                    />
                    <button
                      className="btn-small-primary"
                      disabled={kbBusy}
                      onClick={() => void doRenameKb()}
                    >
                      保存
                    </button>
                    <button
                      className="btn-small"
                      disabled={kbBusy}
                      onClick={() => setKbEditing(false)}
                    >
                      取消
                    </button>
                  </span>
                ) : (
                  <span className="mk-vis-controls">
                    <strong>{kb.display_name}</strong>
                    <button
                      className="btn-small"
                      onClick={() => {
                        setKbNameDraft(kb.display_name ?? "");
                        setKbEditing(true);
                        setKbError(null);
                      }}
                    >
                      编辑名称
                    </button>
                  </span>
                )}
              </div>
              <div className="mk-kb-row">
                <span className="mk-detail-label">状态</span>
                <span
                  className={`mk-vis-pill ${kb.status === "active" ? "mk-vis-asset" : "mk-vis-private"}`}
                >
                  {kbStatusLabel[kb.status ?? ""] ?? kb.status}
                </span>
                {kb.status === "init_failed" && (
                  <button
                    className="btn-small-primary"
                    disabled={kbBusy}
                    onClick={() => void doCreateKb(false)}
                  >
                    {kbBusy ? "重试中…" : "初始化失败，点击重试"}
                  </button>
                )}
              </div>
              <div className="mk-kb-row">
                <span className="mk-detail-label">资产数</span>
                <span>{kb.knowledge_count ?? 0}</span>
              </div>
              <div className="mk-kb-row">
                <span className="mk-detail-label">索引分布</span>
                <span className="mk-vis-controls">
                  {Object.entries(kb.index_distribution ?? {}).length === 0 ? (
                    <span className="mk-vis-note">—</span>
                  ) : (
                    Object.entries(kb.index_distribution ?? {}).map(([st, n]) => (
                      <span key={st} className="al-channel-tag">
                        {indexStatusLabel[st] ?? st}: {n}
                      </span>
                    ))
                  )}
                </span>
              </div>
              <p className="mk-vis-note">
                嵌入模型在知识库创建时绑定，事后更换需全量重索引，此处不开放修改。
              </p>
            </div>
          )}
        </section>
      )}

      <section className="mk-section">
        {forbidden ? (
          <div className="kl-empty-state">
            <div className="kl-empty-title">无个人知识库</div>
            <p className="kl-empty-desc">当前账号没有个人知识库。</p>
          </div>
        ) : loading ? (
          <div className="kl-empty-state">
            <div className="kl-empty-title">加载中…</div>
          </div>
        ) : error ? (
          <div className="kl-empty-state">
            <div className="kl-empty-title">加载失败</div>
            <p className="kl-empty-desc">个人知识暂时无法加载，请稍后重试。</p>
          </div>
        ) : items.length === 0 ? (
          <div className="kl-empty-state">
            <div className="kl-empty-title">暂无个人知识</div>
            <p className="kl-empty-desc">你还没有个人知识资产。</p>
          </div>
        ) : (
          <div className={`mk-split ${selectedItem ? "mk-split-open" : ""}`}>
            <div className="mk-list">
              <h3>知识条目</h3>
              <div className="mk-table-wrap">
                <table className="mk-table">
                  <thead>
                    <tr>
                      <th>标题</th>
                      <th>类型</th>
                      <th>阶段</th>
                      <th>状态</th>
                      <th>更新时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => {
                      const st = zoneStatus(item.zone);
                      return (
                        <tr key={item.id} className={selectedId === item.id ? "mk-row-active" : ""}>
                          <td className="mk-cell-title">{item.title}</td>
                          <td>
                            <span className="mk-type-tag">
                              {typeLabel[item.assetType] ?? item.assetType}
                            </span>
                          </td>
                          <td>{item.lifecyclePhase || "—"}</td>
                          <td>
                            <span className={`mk-vis-pill ${st.cls}`}>{st.label}</span>
                          </td>
                          <td className="mk-cell-time">{item.updatedAt || "—"}</td>
                          <td>
                            <button className="btn-small" onClick={() => setSelectedId(item.id)}>
                              查看
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {selectedItem && (
              <div className="mk-detail">
                <div className="mk-detail-head">
                  <span className="mk-detail-title">知识详情</span>
                  <button className="btn-small" onClick={() => setSelectedId(null)}>
                    关闭
                  </button>
                </div>
                <div className="mk-detail-body">
                  <div className="mk-detail-field">
                    <span className="mk-detail-label">标题</span>
                    <span className="mk-detail-value">{selectedItem.title}</span>
                  </div>
                  <div className="mk-detail-field">
                    <span className="mk-detail-label">一句话摘要</span>
                    <span className="mk-detail-value">{selectedItem.summary || "—"}</span>
                  </div>
                  <div className="mk-detail-field">
                    <span className="mk-detail-label">标签</span>
                    <span className="mk-detail-value">
                      <div className="card-tags">
                        {selectedItem.tags.map((t) => (
                          <span key={t} className="tag">
                            {t}
                          </span>
                        ))}
                      </div>
                    </span>
                  </div>
                  <div className="mk-detail-field">
                    <span className="mk-detail-label">当前状态</span>
                    <span className="mk-detail-value">
                      <span className={`mk-vis-pill ${zoneStatus(selectedItem.zone).cls}`}>
                        {zoneStatus(selectedItem.zone).label}
                      </span>
                    </span>
                  </div>

                  {/* 写动作交互状态 */}
                  {actionError && (
                    <div
                      className="up-submit-notice"
                      style={{ color: "var(--color-danger-fg, #b00)" }}
                    >
                      {actionError}
                    </div>
                  )}
                  {actionNote && (
                    <div
                      className="up-submit-notice"
                      style={{ color: "var(--color-success-fg, #176)" }}
                    >
                      {actionNote}
                    </div>
                  )}

                  {/* 本人资产确认（仅 material） */}
                  {selectedItem.zone !== "asset" && (
                    <div className="mk-detail-field">
                      <span className="mk-detail-label">本人资产确认</span>
                      <span className="mk-detail-value">
                        <button
                          className="btn-small-primary"
                          disabled={actionBusy}
                          onClick={() => void doConfirm(selectedItem.id)}
                        >
                          {actionBusy ? "处理中…" : "确认为本人资产"}
                        </button>
                        <span className="mk-vis-note">
                          本人确认 = 整理为个人知识资产（仅本人可见，不等于项目/公司资产）
                        </span>
                      </span>
                    </div>
                  )}

                  {/* 提交到项目 / 候选 */}
                  <div className="mk-detail-field">
                    <span className="mk-detail-label">提交到项目</span>
                    <span className="mk-detail-value">
                      {hasProjects ? (
                        <div className="mk-vis-controls">
                          <select
                            className="up-edit-select"
                            value={targetProject}
                            onChange={(e) => setTargetProject(e.target.value)}
                          >
                            {projects.map((p) => (
                              <option key={p.projectId} value={p.projectId}>
                                {p.projectName}
                              </option>
                            ))}
                          </select>
                          <button
                            className="btn-small-primary"
                            disabled={actionBusy}
                            onClick={() => void doSubmit(selectedItem.id)}
                          >
                            提交项目资料
                          </button>
                          <button
                            className="btn-small"
                            disabled={actionBusy}
                            onClick={() => setEvidenceMode("internal_sharing")}
                          >
                            发起内部分享候选
                          </button>
                          <button
                            className="btn-small"
                            disabled={actionBusy}
                            onClick={() => setEvidenceMode("client_validation")}
                          >
                            登记客户验证候选
                          </button>
                          <span className="mk-vis-note">
                            提交项目资料 = 待项目经理审核确认；候选 =
                            登记证据线索，系统不自动证明分享/客户验证真实发生
                          </span>
                        </div>
                      ) : (
                        <span className="mk-vis-note">
                          你当前没有可提交的项目，请联系项目负责人添加成员关系。
                        </span>
                      )}
                    </span>
                  </div>

                  {/* 候选证据表单 */}
                  {evidenceMode && hasProjects && (
                    <div className="mk-detail-field">
                      <span className="mk-detail-label">
                        {evidenceMode === "internal_sharing" ? "内部分享候选" : "客户验证候选"}
                      </span>
                      <span className="mk-detail-value">
                        <div className="mk-vis-controls">
                          <select
                            className="up-edit-select"
                            value={evidenceCategory}
                            onChange={(e) => setEvidenceCategory(e.target.value)}
                          >
                            {EVIDENCE_CATEGORIES.map((c) => (
                              <option key={c} value={c}>
                                {evidenceCategoryLabel[c]}
                              </option>
                            ))}
                          </select>
                          <input
                            className="up-edit-input"
                            placeholder="证据说明（如会议主题 / 客户确认要点）"
                            value={evidenceDesc}
                            onChange={(e) => setEvidenceDesc(e.target.value)}
                          />
                          <button
                            className="btn-small-primary"
                            disabled={actionBusy}
                            onClick={() => void doEvidence(selectedItem.id)}
                          >
                            登记候选
                          </button>
                          <button
                            className="btn-small"
                            disabled={actionBusy}
                            onClick={() => setEvidenceMode(null)}
                          >
                            取消
                          </button>
                          <span className="mk-vis-note">
                            仅登记证据线索元数据，不接收真实文件 URL；待项目经理审核。
                          </span>
                        </div>
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="mk-section">
        <div className="mk-action-note">
          个人知识的查看、提交、分享与客户验证登记均受权限与操作记录保护。提交到项目后会进入「待项目经理确认」，通过前不会直接进入项目库。
        </div>
      </section>
    </div>
  );
}
