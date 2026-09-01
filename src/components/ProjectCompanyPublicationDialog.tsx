import { useState } from "react";
import { previewCompanyUpgrade, requestCompanyUpgrade } from "../api/review";
import type { NamingPreviewDTO } from "../types/naming";
import type { AssetStatus } from "../types/knowledge";
import ConfirmDialog from "./ConfirmDialog";
import PublicationNamingFields, {
  createPublicationNamingValue,
  type PublicationNamingValue,
} from "./PublicationNamingFields";

export interface ProjectCompanyPublicationTarget {
  id: string;
  title: string;
}

export interface ProjectCompanyPublicationCandidate {
  scope: string;
  zone: string;
  assetStatus: AssetStatus;
  projectId?: string | null;
}

export interface ProjectCompanyPublicationEligibility {
  eligible: boolean;
  reason: string | null;
}

export function getProjectCompanyPublicationEligibility(
  candidate: ProjectCompanyPublicationCandidate,
  projectId: string,
  projectRole: string | null | undefined,
): ProjectCompanyPublicationEligibility {
  if (candidate.scope !== "project" || (candidate.projectId && candidate.projectId !== projectId)) {
    return { eligible: false, reason: "仅可发布当前项目内的知识资产" };
  }
  if (projectRole !== "project_manager") {
    return { eligible: false, reason: "仅项目经理可提交公司发布申请" };
  }
  if (candidate.zone !== "asset") {
    return { eligible: false, reason: "资料需先完成资产化审核" };
  }
  if (candidate.assetStatus === "archived") {
    return { eligible: false, reason: "已归档资产不能提交公司发布申请" };
  }
  if (candidate.assetStatus !== "active") {
    return { eligible: false, reason: "仅活跃项目资产可提交公司发布申请" };
  }
  return { eligible: true, reason: null };
}

export default function ProjectCompanyPublicationDialog({
  projectId,
  target,
  onClose,
  onSubmitted,
}: {
  projectId: string;
  target: ProjectCompanyPublicationTarget | null;
  onClose: () => void;
  onSubmitted: () => void;
}) {
  if (!target) return null;
  return (
    <ProjectCompanyPublicationSession
      key={`${projectId}:${target.id}`}
      projectId={projectId}
      target={target}
      onClose={onClose}
      onSubmitted={onSubmitted}
    />
  );
}

function ProjectCompanyPublicationSession({
  projectId,
  target,
  onClose,
  onSubmitted,
}: {
  projectId: string;
  target: ProjectCompanyPublicationTarget;
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const [naming, setNaming] = useState<PublicationNamingValue>(() =>
    createPublicationNamingValue(target.title),
  );
  const [preview, setPreview] = useState<NamingPreviewDTO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy) return;
    if (!preview?.canonical_name) {
      setError("请先预览并确认目标文件名");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await requestCompanyUpgrade(projectId, target.id, naming);
      onSubmitted();
    } catch {
      setError("公司发布申请提交失败，请检查目标命名后重试。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      open
      title="发布到公司知识库"
      description="将创建独立的公司知识版本，并进入项目经理与公司知识管理员双角色确认；当前项目资产及项目归属保持不变。"
      confirmText="提交公司发布申请"
      busy={busy}
      error={error}
      errorDescription={error ?? undefined}
      onCancel={() => {
        if (!busy) onClose();
      }}
      onConfirm={() => void submit()}
    >
      <PublicationNamingFields
        scope="company"
        value={naming}
        disabled={busy}
        onChange={setNaming}
        onPreviewed={setPreview}
        onPreview={(value) => previewCompanyUpgrade(projectId, target.id, value)}
      />
    </ConfirmDialog>
  );
}
