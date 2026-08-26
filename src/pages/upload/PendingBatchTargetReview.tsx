import type { Dispatch, SetStateAction } from "react";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { DirectoryOptionDTO, NamingOptionsDTO } from "../../types/naming";
import type { TargetLibrary } from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

type TargetProps = {
  flow: UploadFlow;
  targetLibrary: TargetLibrary;
  targetProjectId: string;
  targetOptionsBusy: boolean;
  targetOptionsError: string | null;
  bulkPersonalDirectoryKey: string;
  bulkCategoryId: string;
  formalDirectories: DirectoryOptionDTO[];
  options: NamingOptionsDTO | null;
  onResetReview: () => void;
  onLibraryChange: (value: TargetLibrary) => void;
  onProjectChange: (value: string) => void;
  onPersonalDirectoryChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
  onRetryOptions: () => void;
};

export function PendingBatchTargetStep(props: TargetProps) {
  const {
    flow,
    targetLibrary,
    targetProjectId,
    targetOptionsBusy,
    targetOptionsError,
    bulkPersonalDirectoryKey,
    bulkCategoryId,
    formalDirectories,
    options,
  } = props;
  return (
    <>
      <label className="upload77-field">
        <span>目标知识库</span>
        <select
          aria-label="批量入库目标知识库"
          value={targetLibrary}
          onChange={(event) => {
            props.onResetReview();
            props.onLibraryChange(event.target.value as TargetLibrary);
          }}
        >
          <option value="">请选择目标知识库</option>
          <option value="personal">个人知识库</option>
          {(flow.projects ?? []).length > 0 && <option value="project">项目知识库</option>}
          {flow.canUseCompanyTarget && <option value="company">公司知识库</option>}
        </select>
      </label>
      {targetLibrary === "project" && (
        <label className="upload77-field">
          <span>具体项目</span>
          <select
            aria-label="批量入库目标项目"
            value={targetProjectId}
            onChange={(event) => {
              props.onResetReview();
              props.onProjectChange(event.target.value);
            }}
          >
            <option value="">请选择目标项目</option>
            {(flow.projects ?? []).map((project) => (
              <option key={project.projectId} value={project.projectId}>
                {project.projectName}
              </option>
            ))}
          </select>
        </label>
      )}
      {targetLibrary === "personal" && (
        <label className="upload77-field">
          <span>本批个人目录</span>
          <select
            aria-label="本批个人目录"
            disabled={targetOptionsBusy}
            value={bulkPersonalDirectoryKey}
            onChange={(event) => props.onPersonalDirectoryChange(event.target.value)}
          >
            <option value="">请选择正式个人目录</option>
            {formalDirectories.map((directory) => (
              <option key={directory.directory_key} value={directory.directory_key}>
                {directory.display_name}
              </option>
            ))}
          </select>
          {!targetOptionsBusy && !targetOptionsError && !bulkPersonalDirectoryKey && (
            <small className="upload77-batch-naming-error">请选择正式个人目录</small>
          )}
          {!targetOptionsBusy &&
            !targetOptionsError &&
            options &&
            formalDirectories.length === 0 && (
              <small className="upload77-batch-naming-error">
                当前没有可用于正式入库的个人目录，请联系管理员。
              </small>
            )}
        </label>
      )}
      {(targetLibrary === "company" ||
        (targetLibrary === "project" && Boolean(targetProjectId))) && (
        <label className="upload77-field">
          <span>本批目录类别</span>
          <select
            aria-label="本批目录类别"
            disabled={targetOptionsBusy}
            value={bulkCategoryId}
            onChange={(event) => props.onCategoryChange(event.target.value)}
          >
            <option value="">暂不统一指定，下一步逐条选择</option>
            {(options?.categories ?? []).map((category) => (
              <option key={category.id} value={category.id}>
                {category.primary} / {category.secondary}
              </option>
            ))}
          </select>
        </label>
      )}
      {targetOptionsError && (
        <div role="alert">
          <span>{targetOptionsError}</span>
          {targetLibrary === "personal" && (
            <button className="btn-secondary" onClick={props.onRetryOptions} type="button">
              重试加载个人目录
            </button>
          )}
        </div>
      )}
    </>
  );
}

type PersonalProps = {
  tasks: PendingIngestItemDTO[];
  directoryLabel: string;
  formalDirectories: DirectoryOptionDTO[];
  directoryByTask: Record<string, string>;
  setDirectoryByTask: Dispatch<SetStateAction<Record<string, string>>>;
  batchErrors: Record<string, string>;
  onOpenAi: (task: PendingIngestItemDTO) => Promise<void>;
};

export function PendingBatchPersonalReview(props: PersonalProps) {
  return (
    <div className="upload77-personal-directory-review">
      <div className="upload77-personal-directory-summary" role="status">
        本批默认进入“{props.directoryLabel}”，可为单条资料调整目录。
      </div>
      <div className="upload77-personal-directory-list">
        {props.tasks.map((task, index) => (
          <article className="upload77-personal-directory-row" key={task.id}>
            <div className="upload77-personal-directory-file">
              <strong title={task.source_file_name}>
                {index + 1}. {task.source_file_name}
              </strong>
              <button
                className="btn-secondary"
                onClick={() => void props.onOpenAi(task)}
                type="button"
              >
                查看 AI 提取
              </button>
            </div>
            <label>
              <span>个人目录</span>
              <select
                aria-label={`${task.source_file_name} 个人目录`}
                value={props.directoryByTask[task.id] ?? ""}
                onChange={(event) =>
                  props.setDirectoryByTask((current) => ({
                    ...current,
                    [task.id]: event.target.value,
                  }))
                }
              >
                <option value="">请选择正式个人目录</option>
                {props.formalDirectories.map((directory) => (
                  <option key={directory.directory_key} value={directory.directory_key}>
                    {directory.display_name}
                  </option>
                ))}
              </select>
            </label>
            {props.batchErrors[task.id] && (
              <div className="upload77-batch-naming-error" role="alert">
                {props.batchErrors[task.id]}
              </div>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
