// 身份与会话：登录 / 登出 / 当前身份（/auth/me）。明文 token 由后端经 httpOnly
// cookie 下发，前端不接触、不存储 token；登录态完全由 cookie + /auth/me 决定。
import {
  BASE_URL,
  clearCsrfToken,
  devHeaders,
  ensureCsrfToken,
  handleResponse,
  apiGet,
  apiPostNoBody,
} from "./http";

// ---- 身份上下文（会话身份；用于顶栏展示与入库时选择目标项目） ----
export interface AuthMeVM {
  userId: string;
  name: string;
  email: string;
  companyRoles: string[];
  isBusinessUser: boolean;
  canDiscoverL5: boolean;
  projects: { projectId: string; projectName: string; projectRole: string }[];
}

interface AuthMeDTO {
  user_id: string;
  name: string;
  email: string;
  status: string;
  company_roles: string[];
  is_business_user: boolean;
  can_discover_l5: boolean;
  project_memberships: { project_id: string; project_name: string; project_role: string; status: string }[];
}

function mapAuthMe(data: AuthMeDTO): AuthMeVM {
  return {
    userId: data.user_id,
    name: data.name,
    email: data.email,
    companyRoles: data.company_roles,
    isBusinessUser: data.is_business_user,
    canDiscoverL5: data.can_discover_l5,
    projects: data.project_memberships
      .filter((m) => m.status === "active")
      .map((m) => ({ projectId: m.project_id, projectName: m.project_name, projectRole: m.project_role })),
  };
}

export async function fetchAuthMe(): Promise<AuthMeVM> {
  return mapAuthMe(await apiGet<AuthMeDTO>(`/api/v1/auth/me`));
}

// 会话登录。提供 password → 所有环境密码登录；不提供 → 仅开发环境无凭证适配器。
// password 仅上送，不回显。登录无需预先持有 CSRF token（后端豁免 /auth/login）。
export async function login(email: string, password?: string): Promise<AuthMeVM> {
  const body: { email: string; password?: string } = { email };
  if (password) body.password = password;
  const resp = await fetch(`${BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: devHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    credentials: "include",
  });
  const me = mapAuthMe(await handleResponse<AuthMeDTO>(resp));
  // 会话已变化 → 清旧 token 并预取绑定新会话的 CSRF token。
  clearCsrfToken();
  await ensureCsrfToken();
  return me;
}

export async function logout(): Promise<void> {
  await apiPostNoBody<{ ok: boolean }>(`/api/v1/auth/logout`);
  // 登出后本地 CSRF token 绑定的会话已失效，清理缓存。
  clearCsrfToken();
}
