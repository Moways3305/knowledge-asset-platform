// 项目领域：项目列表 / 创建、项目设置与成员、项目 Q&A。响应只含安全治理元数据；
// 前端绝不直连外部 Agent / provider，也不拼接任何 provider 内部标识，一律经平台权限网关。
import { apiGet, apiPost, apiPatch } from "./http";
import type {
  ProjectCreateRequestDTO,
  ProjectCreateResponseDTO,
  ProjectListResponseDTO,
  ProjectOverviewDTO,
} from "../types/project";
import type {
  ProjectMemberDTO,
  ProjectMemberPatchDTO,
  ProjectMembersResponseDTO,
  ProjectSettingsDTO,
  ProjectSettingsUpdateDTO,
} from "../types/projectSettings";
import type { ProjectQaModelOptionsResponseDTO, ProjectQaResponseDTO } from "../types/agent";

// 可切换项目只来自当前用户的 active 项目成员关系，公司角色不扩展项目范围。
export async function fetchProjects(): Promise<ProjectListResponseDTO> {
  return apiGet<ProjectListResponseDTO>(`/api/v1/projects`);
}

export async function fetchProjectOverview(projectId: string): Promise<ProjectOverviewDTO> {
  return apiGet<ProjectOverviewDTO>(`/api/v1/projects/${projectId}/overview`);
}

// 创建项目知识空间（仅总经理 / 咨询总监）。写真实 projects + active project_manager 成员。
export async function createProject(
  body: ProjectCreateRequestDTO,
): Promise<ProjectCreateResponseDTO> {
  return apiPost<ProjectCreateResponseDTO>(`/api/v1/projects`, body);
}

// 项目问答。引用层级与可见性由后端按调用人权限裁定；前端只发查询与 capability。
export async function projectQa(
  projectId: string,
  input: { query: string; modelRef: string },
): Promise<ProjectQaResponseDTO> {
  return apiPost<ProjectQaResponseDTO>(`/api/v1/projects/${projectId}/qa`, {
    query: input.query,
    model_ref: input.modelRef,
    capability: "qa",
  });
}

export async function fetchProjectQaModelOptions(
  projectId: string,
): Promise<ProjectQaModelOptionsResponseDTO> {
  return apiGet<ProjectQaModelOptionsResponseDTO>(`/api/v1/projects/${projectId}/qa/model-options`);
}

// ---- 项目设置 / 项目成员 ----
// 读：admin / 治理角色 / 本项目成员；写：项目经理 / 治理角色。
// 响应只含安全治理元数据；企微群只回 bound + 脱敏 label（不回全文）；前端不展示任何内部标识。
export async function fetchProjectSettings(projectId: string): Promise<ProjectSettingsDTO> {
  return apiGet<ProjectSettingsDTO>(`/api/v1/projects/${projectId}/settings`);
}

export async function updateProjectSettings(
  projectId: string,
  body: ProjectSettingsUpdateDTO,
): Promise<ProjectSettingsDTO> {
  return apiPatch<ProjectSettingsDTO>(`/api/v1/projects/${projectId}/settings`, body);
}

export async function fetchProjectMembers(projectId: string): Promise<ProjectMembersResponseDTO> {
  return apiGet<ProjectMembersResponseDTO>(`/api/v1/projects/${projectId}/members`);
}

export async function patchProjectMember(
  projectId: string,
  memberId: string,
  body: ProjectMemberPatchDTO,
): Promise<ProjectMemberDTO> {
  return apiPatch<ProjectMemberDTO>(`/api/v1/projects/${projectId}/members/${memberId}`, body);
}
