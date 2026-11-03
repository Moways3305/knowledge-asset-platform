import { AlertTriangle, Check, ClipboardCheck, RotateCcw, Save, Trash2, X } from "lucide-react";
import { Link } from "react-router-dom";
import ActionFeedback from "../components/ActionFeedback";
import { FormActions } from "../components/ActionLayout";
import ConfirmDialog from "../components/ConfirmDialog";
import LoadingError from "../components/LoadingError";
import { PageHeader, ProductPage } from "../components/ProductLayout";
import ProjectModuleFrame from "../components/ProjectModuleFrame";
import ProjectWorkspaceNav from "../components/ProjectWorkspaceNav";
import StatusBadge from "../components/StatusBadge";
import WorkspaceOutline from "../components/WorkspaceOutline";
import { HistoryBackButton } from "../routing/SafeNavigation";
import { formatBeijingTime } from "../utils/time";
import "./ProjectSettingsPage.css";
import {
  PROJECT_ROLE_OPTIONS,
  memberStatusLabel,
  projectRoleLabel,
  projectStatusLabel,
  reviewTypeLabel,
  routeLabel,
} from "./controllers/ProjectSettings/model";
import { useProjectSettings } from "./controllers/ProjectSettings/useProjectSettings";
import { bizStageOptions } from "./upload/uploadConstants";

export default function ProjectSettingsPage() {
  const {
    loading,
    projectId,
    pageError,
    settings,
    draft,
    loadProject,
    switchProjects,
    switchToProject,
    actionError,
    actionNote,
    canWrite,
    saving,
    setDraft,
    routeOptions,
    historicalPhase,
    dirty,
    discardDraft,
    saveDraft,
    canEditProjectRoles,
    addMemberOpen,
    openAddMemberForm,
    members,
    memberBusy,
    changeMember,
    handleRemoveMember,
    addMemberQuery,
    setAddMemberQuery,
    filterCandidates,
    addMemberUserId,
    setAddMemberUserId,
    addMemberCandidates,
    addMemberRole,
    setAddMemberRole,
    addMemberError,
    addMemberBusy,
    submitAddMember,
    setAddMemberOpen,
    setAddMemberError,
    reviewsLoading,
    reviews,
    reviewsError,
    loadReviews,
    reviewBusy,
    approveProjectReview,
    openRejectDialog,
    canDelete,
    dangerError,
    deleteDialogOpen,
    assetCount,
    dangerBusy,
    setDeleteConfirmName,
    setDangerError,
    setDeleteDialogOpen,
    memberCount,
    removeTarget,
    confirmRemoveMember,
    setRemoveTarget,
    deleteConfirmName,
    handleDelete,
    rejectTarget,
    rejectError,
    submitReject,
    setRejectTarget,
    setRejectReason,
    setRejectError,
    rejectReason,
  } = useProjectSettings();

  if (loading) {
    return (
      <ProjectModuleFrame
        navigation={
          projectId ? (
            <ProjectWorkspaceNav projectId={projectId} current="settings" canManage />
          ) : (
            <Link to="/projects">返回项目列表</Link>
          )
        }
      >
        <ProductPage className="project-settings-page">
          <LoadingError
            loading
            loadingTitle="正在加载项目设置…"
            wrapperClassName="ps74-page-state"
          />
        </ProductPage>
      </ProjectModuleFrame>
    );
  }

  if (pageError || !settings || !draft || !projectId) {
    return (
      <ProjectModuleFrame
        navigation={
          projectId ? (
            <ProjectWorkspaceNav projectId={projectId} current="settings" canManage />
          ) : (
            <Link to="/projects">返回项目列表</Link>
          )
        }
      >
        <ProductPage className="project-settings-page">
          <LoadingError
            error={pageError ?? "当前项目不可用"}
            errorTitle="无法加载项目设置"
            errorDescription={pageError ?? "当前项目不可用"}
            onRetry={projectId ? () => void loadProject(projectId) : undefined}
            wrapperClassName="ps74-page-state"
          />
        </ProductPage>
      </ProjectModuleFrame>
    );
  }

  return (
    <ProjectModuleFrame
      navigation={<ProjectWorkspaceNav projectId={projectId} current="settings" canManage />}
    >
      <ProductPage className="project-settings-page">
        <PageHeader
          className="ps74-header"
          title={settings.name}
          description="管理项目入库策略、企微群绑定与项目成员关系。"
          status={
            <StatusBadge
              label={projectStatusLabel[settings.status] ?? "项目状态未知"}
              variant={`ps74-status is-${settings.status}`}
              tone={settings.status === "active" ? "success" : "neutral"}
            />
          }
          actions={
            <>
              <HistoryBackButton
                className="product-button is-secondary"
                fallback={`/project/${projectId}/knowledge`}
              >
                返回项目知识库
              </HistoryBackButton>
              {switchProjects.length > 1 && (
                <label className="ps74-project-switcher">
                  <span>切换项目</span>
                  <select
                    value={projectId}
                    onChange={(event) => switchToProject(event.target.value)}
                  >
                    {switchProjects.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          }
        />

        {actionError && (
          <ActionFeedback
            state="error"
            title="设置未保存"
            description={actionError}
            nextStep="检查输入后重试；当前编辑内容仍会保留。"
          />
        )}
        {actionNote && (
          <ActionFeedback state="success" title="设置已更新" description={actionNote} />
        )}
        {!canWrite && (
          <ActionFeedback
            state="info"
            title="当前为只读模式"
            description="当前身份可查看项目设置，修改仅由本项目经理完成。"
          />
        )}

        <WorkspaceOutline
          label="项目设置分区"
          items={[
            { id: "project-basic-heading", label: "基本信息" },
            { id: "project-policy-heading", label: "命名与入库" },
            { id: "project-members-heading", label: "项目成员" },
            { id: "pending-review-heading", label: "待审核事项" },
            { id: "project-danger-heading", label: "删除项目" },
          ]}
        >
          <div className="ps74-layout">
            <div className="ps74-main-column">
              <section className="ps74-section" aria-labelledby="project-basic-heading">
                <div className="ps74-section-header">
                  <div>
                    <h2 id="project-basic-heading" tabIndex={-1}>
                      项目基本信息
                    </h2>
                    <p>以下信息来自项目治理记录，仅供查看。</p>
                  </div>
                </div>
                <dl className="ps74-info-grid">
                  <div>
                    <dt>项目名称</dt>
                    <dd>{settings.name}</dd>
                  </div>
                  <div>
                    <dt>客户名称</dt>
                    <dd>{settings.client_name ?? "未提供"}</dd>
                  </div>
                  <div>
                    <dt>项目状态</dt>
                    <dd>{projectStatusLabel[settings.status] ?? "状态未知"}</dd>
                  </div>
                  <div>
                    <dt>辅导老师</dt>
                    <dd>{settings.coach_name ?? "暂未设置"}</dd>
                  </div>
                  <div>
                    <dt>最近更新</dt>
                    <dd>{formatBeijingTime(settings.updated_at)}</dd>
                  </div>
                </dl>
              </section>

              <section className="ps74-section" aria-labelledby="project-policy-heading">
                <div className="ps74-section-header">
                  <div>
                    <h2 id="project-policy-heading" tabIndex={-1}>
                      项目命名、入库策略与企微群绑定
                    </h2>
                    <p>设置只在统一保存成功后生效。</p>
                  </div>
                </div>
                <div className="ps74-settings-grid">
                  <label>
                    <span>项目代码</span>
                    <input
                      value={draft.projectCode}
                      disabled={!canWrite || saving}
                      maxLength={20}
                      placeholder="例如 RAD-01"
                      onChange={(event) =>
                        setDraft((current) =>
                          current
                            ? { ...current, projectCode: event.target.value.toUpperCase() }
                            : current,
                        )
                      }
                    />
                    <small>2–20 位大写字母、数字或短横线；全公司唯一。</small>
                  </label>
                  <label>
                    <span>项目默认密级</span>
                    <select
                      value={draft.namingDefaultConfidentiality}
                      disabled={!canWrite || saving}
                      onChange={(event) =>
                        setDraft((current) =>
                          current
                            ? { ...current, namingDefaultConfidentiality: event.target.value }
                            : current,
                        )
                      }
                    >
                      {["L1", "L2", "L3", "L4", "L5"].map((level) => (
                        <option key={level}>{level}</option>
                      ))}
                    </select>
                  </label>
                  <label className="ps74-switch-row">
                    <span>
                      <strong>启用项目代码</strong>
                      <small>启用后，项目资料规范名使用该项目代码。</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={draft.projectCodeActive}
                      disabled={!canWrite || saving || !draft.projectCode.trim()}
                      onChange={(event) =>
                        setDraft((current) =>
                          current
                            ? { ...current, projectCodeActive: event.target.checked }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label>
                    <span>生命周期路线</span>
                    <select
                      value={draft.lifecycleRouteKey}
                      disabled={!canWrite || saving}
                      onChange={(event) =>
                        setDraft((current) =>
                          current ? { ...current, lifecycleRouteKey: event.target.value } : current,
                        )
                      }
                    >
                      {routeOptions.map((route) => (
                        <option key={route} value={route}>
                          {routeLabel[route] ?? route}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>当前阶段</span>
                    <select
                      value={draft.lifecyclePhaseKey}
                      disabled={!canWrite || saving}
                      name="lifecycle-phase-key"
                      onChange={(event) =>
                        setDraft((current) =>
                          current ? { ...current, lifecyclePhaseKey: event.target.value } : current,
                        )
                      }
                    >
                      <option value="">未设置</option>
                      {historicalPhase && (
                        <option value={historicalPhase}>历史阶段：{historicalPhase}</option>
                      )}
                      {bizStageOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="ps74-switch-row">
                    <span>
                      <strong>入库必须审核</strong>
                      <small>开启后，项目入库任务统一进入项目经理确认。</small>
                    </span>
                    <input
                      type="checkbox"
                      checked={draft.forceReviewOnIngest}
                      disabled={!canWrite || saving}
                      onChange={(event) =>
                        setDraft((current) =>
                          current
                            ? { ...current, forceReviewOnIngest: event.target.checked }
                            : current,
                        )
                      }
                    />
                  </label>
                  <div className="ps74-wecom-setting">
                    <div className="ps74-wecom-status">
                      <span>企微群绑定</span>
                      <strong>
                        {settings.wecom_group_bound
                          ? `已绑定（${settings.wecom_group_label ?? "脱敏标签不可用"}）`
                          : "未绑定"}
                      </strong>
                    </div>
                    {canWrite && (
                      <div className="ps74-wecom-controls">
                        <label>
                          <span className="sr-only">新的企微群绑定标识</span>
                          <input
                            type="password"
                            autoComplete="new-password"
                            name="wecom-binding-token"
                            placeholder="输入新的企微群绑定标识"
                            value={draft.wecomGroupId ?? ""}
                            disabled={saving}
                            onChange={(event) =>
                              setDraft((current) =>
                                current
                                  ? { ...current, wecomGroupId: event.target.value }
                                  : current,
                              )
                            }
                          />
                        </label>
                        {settings.wecom_group_bound && (
                          <button
                            type="button"
                            className="product-button is-secondary is-small"
                            disabled={saving}
                            onClick={() =>
                              setDraft((current) =>
                                current ? { ...current, wecomGroupId: "" } : current,
                              )
                            }
                          >
                            解除绑定
                          </button>
                        )}
                      </div>
                    )}
                    <small>当前绑定仅展示后端提供的脱敏标签，新值不会在保存后回显。</small>
                  </div>
                </div>
                {canWrite && dirty && (
                  <FormActions
                    sticky
                    description="仅保存本区的命名、入库策略与企微绑定设置。"
                    className="ps74-save-actions"
                  >
                    <button
                      className="product-button is-secondary"
                      disabled={saving}
                      onClick={discardDraft}
                    >
                      <RotateCcw size={16} aria-hidden="true" />
                      放弃未保存
                    </button>
                    <button
                      className="product-button is-primary"
                      disabled={saving}
                      onClick={() => void saveDraft()}
                    >
                      <Save size={16} aria-hidden="true" />
                      {saving ? "保存中…" : "保存设置"}
                    </button>
                  </FormActions>
                )}
              </section>

              <section className="ps74-section" aria-labelledby="project-members-heading">
                <div className="ps74-section-header">
                  <div>
                    <h2 id="project-members-heading" tabIndex={-1}>
                      项目成员与项目内角色
                    </h2>
                    <p>
                      成员操作单独提交并立即生效，不需要点击“保存设置”。项目经理身份在此不可调整。
                    </p>
                  </div>
                  {canEditProjectRoles && !addMemberOpen && (
                    <button
                      type="button"
                      className="product-button is-secondary is-small"
                      onClick={openAddMemberForm}
                    >
                      添加成员
                    </button>
                  )}
                </div>
                <div className="ps74-table-wrap">
                  <table data-responsive-table className="ps74-members-table">
                    <thead>
                      <tr>
                        <th>成员</th>
                        <th>项目内角色</th>
                        <th>成员状态</th>
                        <th>加入时间</th>
                        {canEditProjectRoles && (
                          <th className="ps74-member-actions-heading">操作</th>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {members.map((member) => {
                        const editable =
                          canEditProjectRoles && member.project_role !== "project_manager";
                        const busy = memberBusy === member.member_id;
                        return (
                          <tr
                            key={member.member_id}
                            className={member.status !== "active" ? "is-muted" : ""}
                          >
                            <td data-label="成员" className="ps74-member-name">
                              {member.name}
                            </td>
                            <td data-label="项目内角色">
                              {editable ? (
                                <select
                                  aria-label={`调整${member.name}的项目内角色`}
                                  value={member.project_role}
                                  disabled={busy}
                                  onChange={(event) =>
                                    void changeMember(member, { project_role: event.target.value })
                                  }
                                >
                                  {PROJECT_ROLE_OPTIONS.map((role) => (
                                    <option key={role} value={role}>
                                      {projectRoleLabel[role]}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <span className={`ps74-role is-${member.project_role}`}>
                                  {projectRoleLabel[member.project_role] ?? "项目成员"}
                                </span>
                              )}
                            </td>
                            <td data-label="成员状态">
                              {memberStatusLabel[member.status] ?? "状态未知"}
                            </td>
                            <td data-label="加入时间">{formatBeijingTime(member.joined_at)}</td>
                            {canEditProjectRoles && (
                              <td data-label="操作" className="ps74-member-actions">
                                <div className="ps74-member-action-controls">
                                  {editable ? (
                                    <>
                                      <button
                                        className="product-button is-secondary is-small"
                                        disabled={busy}
                                        onClick={() =>
                                          void changeMember(member, {
                                            status:
                                              member.status === "active" ? "inactive" : "active",
                                          })
                                        }
                                      >
                                        {member.status === "active" ? "停用" : "启用"}
                                      </button>
                                      <button
                                        className="product-button is-danger is-small"
                                        disabled={busy}
                                        onClick={() => void handleRemoveMember(member)}
                                      >
                                        移除
                                      </button>
                                    </>
                                  ) : (
                                    <span className="ps74-locked-role">由治理角色任命</span>
                                  )}
                                </div>
                              </td>
                            )}
                          </tr>
                        );
                      })}
                      {members.length === 0 && (
                        <tr>
                          <td colSpan={canEditProjectRoles ? 5 : 4} className="ps74-table-empty">
                            当前项目暂无成员记录
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
                {canEditProjectRoles && (
                  <div className="ps74-member-action-row">
                    {addMemberOpen && (
                      <div className="ps74-add-member-form">
                        <div className="ps74-add-member-fields">
                          <label>
                            <span>搜索用户</span>
                            <input
                              type="text"
                              placeholder="输入姓名搜索"
                              value={addMemberQuery}
                              autoComplete="off"
                              onChange={(event) => {
                                setAddMemberQuery(event.target.value);
                                filterCandidates(event.target.value);
                              }}
                            />
                          </label>
                          <label>
                            <span>选择用户</span>
                            <select
                              value={addMemberUserId}
                              onChange={(event) => setAddMemberUserId(event.target.value)}
                            >
                              <option value="">请选择用户</option>
                              {addMemberCandidates.map((person) => (
                                <option key={person.user_id} value={person.user_id}>
                                  {person.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>项目内角色</span>
                            <select
                              value={addMemberRole}
                              onChange={(event) => setAddMemberRole(event.target.value)}
                            >
                              {PROJECT_ROLE_OPTIONS.map((role) => (
                                <option key={role} value={role}>
                                  {projectRoleLabel[role]}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                        {addMemberError && (
                          <div className="ps74-feedback is-error">{addMemberError}</div>
                        )}
                        <div className="ps74-add-member-actions">
                          <button
                            type="button"
                            className="product-button is-primary is-small"
                            disabled={addMemberBusy || !addMemberUserId}
                            onClick={() => void submitAddMember()}
                          >
                            {addMemberBusy ? "添加中…" : "确认添加"}
                          </button>
                          <button
                            type="button"
                            className="product-button is-secondary is-small"
                            disabled={addMemberBusy}
                            onClick={() => {
                              setAddMemberOpen(false);
                              setAddMemberError(null);
                            }}
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </section>
            </div>

            <aside className="ps74-review-column" aria-labelledby="pending-review-heading">
              <div className="ps74-review-header">
                <div>
                  <h2 id="pending-review-heading" tabIndex={-1}>
                    <ClipboardCheck size={18} aria-hidden="true" />
                    待项目经理确认
                  </h2>
                  <p>仅显示当前项目中可由当前身份处理的记录。</p>
                </div>
                {canWrite && !reviewsLoading && <span>{reviews.length}</span>}
              </div>

              {!canWrite ? (
                <div className="ps74-review-state">
                  <strong>当前身份无确认权限</strong>
                  <p>待确认处理仅向本项目经理开放。</p>
                </div>
              ) : reviewsLoading ? (
                <div className="ps74-review-state" role="status">
                  正在加载待确认任务…
                </div>
              ) : reviewsError ? (
                <div className="ps74-review-state is-error">
                  <strong>待确认任务加载失败</strong>
                  <p>{reviewsError}</p>
                  <button
                    className="product-button is-secondary is-small"
                    onClick={() => void loadReviews(projectId)}
                  >
                    重试
                  </button>
                </div>
              ) : reviews.length === 0 ? (
                <div className="ps74-review-state">
                  <strong>暂无待确认任务</strong>
                  <p>当前项目没有需要你处理的记录。</p>
                </div>
              ) : (
                <div className="ps74-review-list">
                  {reviews.map((review) => {
                    const busy = reviewBusy === review.id;
                    return (
                      <article key={review.id} className="ps74-review-item">
                        <span className="ps74-review-type">
                          {reviewTypeLabel[review.review_type] ?? "项目知识确认"}
                        </span>
                        <h3>{review.asset_title ?? "待确认项目知识"}</h3>
                        <p>
                          {review.status === "approval_failed"
                            ? "上次入库失败，可重新确认"
                            : "等待项目经理确认"}
                          {review.created_at ? ` · ${formatBeijingTime(review.created_at)}` : ""}
                        </p>
                        <div className="ps74-review-actions">
                          <Link
                            to={`/review?review_id=${encodeURIComponent(review.id)}&project_id=${encodeURIComponent(projectId)}`}
                            className="product-button is-secondary is-small"
                          >
                            查看
                          </Link>
                          {review.can_decide && (
                            <>
                              <button
                                className="product-button is-primary is-small"
                                disabled={busy}
                                onClick={() => void approveProjectReview(review)}
                              >
                                <Check size={15} aria-hidden="true" />
                                通过
                              </button>
                              <button
                                className="product-button is-danger is-small"
                                disabled={busy}
                                onClick={() => openRejectDialog(review)}
                              >
                                <X size={15} aria-hidden="true" />
                                驳回
                              </button>
                            </>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </aside>
          </div>

          {canDelete && (
            <section
              className="ps74-section ps74-danger-zone"
              aria-labelledby="project-danger-heading"
            >
              <div className="ps74-section-header">
                <div>
                  <h2 id="project-danger-heading" tabIndex={-1}>
                    删除项目
                  </h2>
                  <p>项目经理可删除没有知识资产的项目；此操作不可恢复。</p>
                </div>
              </div>
              {dangerError && !deleteDialogOpen && (
                <div className="ps74-feedback is-error">{dangerError}</div>
              )}
              {assetCount > 0 ? (
                <div className="ps74-delete-blocker" role="status">
                  <AlertTriangle size={18} aria-hidden="true" />
                  <div>
                    <strong>仍有 {assetCount} 个项目知识资产</strong>
                    <p>先清理项目知识资产后再删除，避免误删仍在使用的内容。</p>
                  </div>
                  <Link
                    className="product-button is-secondary"
                    to={`/project/${projectId}/knowledge`}
                  >
                    前往项目知识库
                  </Link>
                </div>
              ) : (
                <div className="ps74-danger-actions">
                  <button
                    type="button"
                    className="product-button is-danger"
                    disabled={dangerBusy}
                    aria-describedby="project-delete-readiness"
                    onClick={() => {
                      setDeleteConfirmName("");
                      setDangerError(null);
                      setDeleteDialogOpen(true);
                    }}
                  >
                    <Trash2 size={16} aria-hidden="true" />
                    删除项目
                  </button>
                  <p id="project-delete-readiness" className="ps74-delete-readiness">
                    删除将一并移除 {memberCount} 条项目成员关系。
                  </p>
                </div>
              )}
            </section>
          )}
          <ConfirmDialog
            open={Boolean(removeTarget)}
            title={`确认移除成员“${removeTarget?.name ?? ""}”？`}
            description="此操作不可恢复；成员将从该项目移除，其已提交的项目知识不受影响。"
            confirmText="移除成员"
            busyText="移除中…"
            busy={memberBusy !== null}
            danger
            error={actionError}
            errorDescription={actionError}
            onConfirm={() => void confirmRemoveMember()}
            onCancel={() => setRemoveTarget(null)}
          />
          <ConfirmDialog
            open={deleteDialogOpen}
            title={`删除项目“${settings.name}”`}
            description={`此操作不可恢复，并会一并移除 ${memberCount} 条项目成员关系。服务端将在执行前再次校验资产数量和有效项目经理身份。`}
            confirmText="删除项目"
            busyText="删除中…"
            busy={dangerBusy}
            confirmDisabled={deleteConfirmName.trim() !== settings.name}
            danger
            error={dangerError}
            errorDescription={dangerError}
            onConfirm={() => void handleDelete()}
            onCancel={() => {
              setDeleteDialogOpen(false);
              setDeleteConfirmName("");
              setDangerError(null);
            }}
          >
            <label className="ps74-delete-confirm-field">
              <span>输入项目名称“{settings.name}”确认删除</span>
              <input
                type="text"
                value={deleteConfirmName}
                disabled={dangerBusy}
                onChange={(event) => setDeleteConfirmName(event.target.value)}
                autoComplete="off"
              />
            </label>
          </ConfirmDialog>
          <ConfirmDialog
            open={Boolean(rejectTarget)}
            title="驳回项目知识"
            description={
              rejectTarget?.asset_title
                ? `请说明“${rejectTarget.asset_title}”未通过的具体原因。`
                : "请说明该项目知识未通过的具体原因。"
            }
            confirmText="确认驳回"
            busyText="驳回中…"
            busy={Boolean(rejectTarget && reviewBusy === rejectTarget.id)}
            danger
            error={rejectError}
            errorDescription={rejectError}
            onConfirm={() => void submitReject()}
            onCancel={() => {
              setRejectTarget(null);
              setRejectReason("");
              setRejectError(null);
            }}
          >
            <div className="ps74-reject-field">
              <label htmlFor="project-review-reject-reason">驳回理由</label>
              <textarea
                id="project-review-reject-reason"
                aria-describedby="project-review-reject-hint"
                autoFocus
                rows={4}
                maxLength={500}
                value={rejectReason}
                disabled={Boolean(rejectTarget && reviewBusy === rejectTarget.id)}
                onChange={(event) => {
                  setRejectReason(event.target.value);
                  if (rejectError) setRejectError(null);
                }}
                placeholder="填写需要补充或修正的具体内容"
              />
              <small id="project-review-reject-hint">
                该理由将随审核记录保存，并反馈给提交人。
              </small>
            </div>
          </ConfirmDialog>
        </WorkspaceOutline>
      </ProductPage>
    </ProjectModuleFrame>
  );
}
