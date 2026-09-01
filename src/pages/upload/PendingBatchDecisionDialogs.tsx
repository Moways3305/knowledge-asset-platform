import ConfirmDialog from "../../components/ConfirmDialog";
import DangerConfirmDialog from "../../components/DangerConfirmDialog";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { BatchNamingValuesDTO, DirectoryOptionDTO } from "../../types/naming";
import type { PreviewRows } from "./pendingBatchReviewState";
import type { TargetLibrary } from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

type Props = {
  fallbackDirectoryTaskId: string | null;
  fallbackDirectoryKey: string;
  formalDirectories: DirectoryOptionDTO[];
  targetLibrary: TargetLibrary;
  onFallbackKeyChange: (value: string) => void;
  onCancelFallback: () => void;
  onSaveFallback: (taskId: string, patch: Partial<BatchNamingValuesDTO>) => void;
  closeGuardOpen: boolean;
  onCancelCloseGuard: () => void;
  onConfirmCloseGuard: () => void;
  confirmCandidate: PendingIngestItemDTO | null;
  previews: PreviewRows;
  confirmingTaskId: string | null;
  onCancelConfirm: () => void;
  onConfirmOne: () => void;
  deleteCandidate: PendingIngestItemDTO | null;
  deletingTaskId: string | null;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
  rejectOpen: boolean;
  selectedRejectTasks: PendingIngestItemDTO[];
  flow: UploadFlow;
  onCancelReject: () => void;
};

export default function PendingBatchDecisionDialogs(props: Props) {
  const notices = props.confirmCandidate
    ? (props.previews[props.confirmCandidate.id]?.notices ?? [])
    : [];
  return (
    <>
      <ConfirmDialog
        open={props.fallbackDirectoryTaskId !== null}
        title={`选择正式${props.targetLibrary === "company" ? "公司" : "项目"}目录`}
        description="选择后将以该正式目录重新生成规范名预览。"
        confirmText="保存并重新预览"
        confirmDisabled={
          !props.fallbackDirectoryKey ||
          !props.formalDirectories.some((item) => item.directory_key === props.fallbackDirectoryKey)
        }
        onCancel={props.onCancelFallback}
        onConfirm={() => {
          if (!props.fallbackDirectoryTaskId || !props.fallbackDirectoryKey) return;
          props.onSaveFallback(props.fallbackDirectoryTaskId, {
            directory_key: props.fallbackDirectoryKey,
          });
          props.onCancelFallback();
        }}
      >
        <label className="upload77-field">
          <span>正式目录</span>
          <select
            aria-label={`正式${props.targetLibrary === "company" ? "公司" : "项目"}目录`}
            value={props.fallbackDirectoryKey}
            onChange={(event) => props.onFallbackKeyChange(event.target.value)}
          >
            <option value="">请选择正式目录</option>
            {props.formalDirectories.map((directory) => (
              <option key={directory.directory_key} value={directory.directory_key}>
                {directory.display_name}
              </option>
            ))}
          </select>
        </label>
      </ConfirmDialog>

      <ConfirmDialog
        open={props.closeGuardOpen}
        title="放弃本次批量命名核对？"
        description="存在未保存修改或仍在进行的本地预览。关闭后将清理这些状态，已选择的待确认资料不会被删除。"
        confirmText="放弃修改并关闭"
        onCancel={props.onCancelCloseGuard}
        onConfirm={props.onConfirmCloseGuard}
      />

      <ConfirmDialog
        open={props.confirmCandidate !== null}
        title="确认将这条资料入库？"
        description={
          props.confirmCandidate
            ? `${props.previews[props.confirmCandidate.id]?.canonical_name ?? "规范名待校验"} · ${
                props.targetLibrary === "project" ? "项目知识库" : "公司知识库"
              }`
            : undefined
        }
        confirmText={notices.length > 0 ? "仍然确认入库" : "确认入库"}
        busyText="正在确认入库"
        busy={props.confirmingTaskId !== null}
        onCancel={props.onCancelConfirm}
        onConfirm={props.onConfirmOne}
      >
        {props.confirmCandidate && notices.length > 0 && (
          <div className="upload77-batch-naming-notice">
            <strong>请确认以下提示：</strong>
            {notices.map((notice) => (
              <div key={`${notice.code ?? notice.kind}-${notice.message}`}>{notice.message}</div>
            ))}
            <p>继续后会创建独立资料，不会覆盖已有资产。</p>
          </div>
        )}
      </ConfirmDialog>

      <DangerConfirmDialog
        open={props.deleteCandidate !== null}
        title="永久删除这条错误上传资料？"
        description="确认后将永久删除该错误上传资料，不会创建知识资产，操作不可恢复。"
        confirmText="确认永久删除"
        busyText="正在永久删除"
        busy={props.deletingTaskId !== null}
        onCancel={props.onCancelDelete}
        onConfirm={props.onConfirmDelete}
      />

      <DangerConfirmDialog
        open={props.rejectOpen}
        title={`永久拒绝选中的 ${props.selectedRejectTasks.length} 条待确认任务？`}
        description={`确认后将严格逐条删除这 ${props.selectedRejectTasks.length} 条待确认任务，操作不可恢复，且不会创建知识资产。`}
        confirmText="确认永久拒绝"
        busyText="正在逐条拒绝"
        busy={props.flow.batchBusy && props.flow.batchOperation === "reject"}
        onCancel={props.onCancelReject}
        onConfirm={() => {
          props.onCancelReject();
          void props.flow.handleBatchReject(props.selectedRejectTasks);
        }}
      />
    </>
  );
}
