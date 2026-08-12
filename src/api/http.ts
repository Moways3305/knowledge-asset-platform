// HTTP 核心：统一 base URL、开发态身份头（X-Dev-User-Id）、CSRF token 处理、
// 错误归一化，以及各 HTTP 动词的薄封装。各领域 API 模块只在此之上拼装路径与 DTO，
// 页面组件不直接写 fetch / CSRF / 错误细节。

// 默认走 Vite 的 /api 代理；也可用 VITE_API_BASE_URL 覆盖为绝对地址。
import { invalidateTaskStatus } from "../workbench/taskStatusEvents";

export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

// 开发态身份覆盖：本地联调时用 X-Dev-User-Id 指定调用人，方便切换角色。
// 正式登录态已由后端 httpOnly cookie 会话（kap_session）承载（见 auth 模块）；
// 该 header 仅在设置 VITE_DEV_USER_ID 时附带，留空则完全走 cookie 会话。
const DEV_USER_ID = import.meta.env.VITE_DEV_USER_ID ?? "";

export class ApiError extends Error {
  status: number;
  deniedReason?: string;
  // 错误响应 detail 对象（安全字段，如 missing_config 项名）；不含敏感值。
  detail?: Record<string, unknown>;
  constructor(
    status: number,
    message: string,
    deniedReason?: string,
    detail?: Record<string, unknown>,
  ) {
    super(message);
    this.status = status;
    this.deniedReason = deniedReason;
    this.detail = detail;
  }
}

export function devHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  if (DEV_USER_ID) headers["X-Dev-User-Id"] = DEV_USER_ID;
  return headers;
}

// ---- CSRF ----
// CSRF token 仅内存缓存（非认证凭证，绝不写入 localStorage / sessionStorage）；
// 后端对 cookie 会话下的 unsafe 请求强制校验，dev 的 X-Dev-User-Id 回退不受影响。
let _csrfToken: string | null = null;
let _csrfInflight: Promise<string> | null = null;

async function fetchCsrfToken(): Promise<string> {
  const resp = await fetch(`${BASE_URL}/api/v1/auth/csrf`, {
    headers: devHeaders(),
    credentials: "include",
  });
  const body = (await resp.json()) as { csrf_token: string };
  _csrfToken = body.csrf_token;
  return _csrfToken;
}

export async function ensureCsrfToken(): Promise<string> {
  if (_csrfToken) return _csrfToken;
  if (!_csrfInflight) {
    _csrfInflight = fetchCsrfToken().finally(() => {
      _csrfInflight = null;
    });
  }
  return _csrfInflight;
}

// 清空缓存（登录/登出后会话变化 → token 绑定失效，须重取）。
export function clearCsrfToken(): void {
  _csrfToken = null;
}

// 为 unsafe 请求附带 X-CSRF-Token（不覆盖调用方显式传入的同名头）。
export async function csrfHeaders(
  extra: Record<string, string> = {},
): Promise<Record<string, string>> {
  const headers = devHeaders(extra);
  if (!("X-CSRF-Token" in headers)) headers["X-CSRF-Token"] = await ensureCsrfToken();
  return headers;
}

function isCsrfDenied(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    err.status === 403 &&
    typeof err.deniedReason === "string" &&
    err.deniedReason.startsWith("csrf_token_")
  );
}

// unsafe 请求统一执行器：CSRF 失败时刷新一次 token 重试（仅一次，避免循环）。
export async function withCsrfRetry<T>(send: () => Promise<T>): Promise<T> {
  try {
    return await send();
  } catch (err) {
    if (!isCsrfDenied(err)) throw err;
    clearCsrfToken();
    await ensureCsrfToken();
    return send(); // 仅重试一次
  }
}

export async function handleResponse<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let deniedReason: string | undefined;
    // 默认文案不含 HTTP code / 接口路径 / trace 等技术细节；status 仅留在 ApiError.status 供逻辑判定。
    let message = "请求未成功，请稍后重试";
    let detailObj: Record<string, unknown> | undefined;
    try {
      const body = await resp.json();
      const detail = body?.detail;
      if (detail && typeof detail === "object") {
        deniedReason = detail.denied_reason;
        message = detail.message ?? message;
        detailObj = detail as Record<string, unknown>;
      }
    } catch {
      // 忽略非 JSON 错误体
    }

    // 403 提供更友好的错误提示，帮助用户理解是否需要切换身份
    if (resp.status === 403) {
      if (deniedReason === "project_manager_appointment_requires_governance") {
        message = "任命项目经理需要总经理或咨询总监身份，请在右上角身份菜单中切换角色后重试。";
      } else if (deniedReason === "active_company_role_not_assigned") {
        message = "该身份尚未分配给你，需管理员在人员名册中先分配。";
      } else if (
        deniedReason === "people_governance_required" ||
        deniedReason === "people_admin_forbidden"
      ) {
        message = "当前操作需要治理权限（总经理/咨询总监），请检查你当前的活跃身份。";
      }
    }

    throw new ApiError(resp.status, message, deniedReason, detailObj);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

// 所有请求带上 credentials，使会话 cookie（kap_session, httpOnly）随同发送。
// 同源经 Vite /api 代理时 cookie 正常工作；X-Dev-User-Id 仍作为开发态回退。
export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: devHeaders(),
    credentials: "include",
  });
  return handleResponse<T>(resp);
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  return withCsrfRetry(async () => {
    const resp = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: await csrfHeaders({ "Content-Type": "application/json", ...extraHeaders }),
      body: JSON.stringify(body),
      credentials: "include",
    });
    const result = await handleResponse<T>(resp);
    invalidateTaskStatus(path);
    return result;
  });
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return withCsrfRetry(async () => {
    const resp = await fetch(`${BASE_URL}${path}`, {
      method: "PATCH",
      headers: await csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      credentials: "include",
    });
    const result = await handleResponse<T>(resp);
    invalidateTaskStatus(path);
    return result;
  });
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  return withCsrfRetry(async () => {
    const resp = await fetch(`${BASE_URL}${path}`, {
      method: "PUT",
      headers: await csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      credentials: "include",
    });
    const result = await handleResponse<T>(resp);
    invalidateTaskStatus(path);
    return result;
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return withCsrfRetry(async () => {
    const resp = await fetch(`${BASE_URL}${path}`, {
      method: "DELETE",
      headers: await csrfHeaders(),
      credentials: "include",
    });
    const result = await handleResponse<T>(resp);
    invalidateTaskStatus(path);
    return result;
  });
}

// 无请求体的 POST（如标记处理 / 触发扫描 / 登出）。仍走 CSRF 重试包装。
export async function apiPostNoBody<T>(
  path: string,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  return withCsrfRetry(async () => {
    const resp = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: await csrfHeaders({ "Content-Type": "application/json", ...extraHeaders }),
      body: "{}",
      credentials: "include",
    });
    const result = await handleResponse<T>(resp);
    invalidateTaskStatus(path);
    return result;
  });
}

// 仅作客户端幂等用途的 key（非密钥、不含任何用户/业务数据，不打日志）。
// 优先 randomUUID；退而用 getRandomValues；都不可用时用 timestamp + 单调计数器兜底（非伪随机）。
let idempotencyCounter = 0;
export function createIdempotencyKey(): string {
  const c = typeof crypto !== "undefined" ? crypto : undefined;
  if (c && typeof c.randomUUID === "function") {
    return c.randomUUID();
  }
  if (c && typeof c.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    c.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  }
  idempotencyCounter += 1;
  return `${Date.now()}-${idempotencyCounter}`;
}

export function createClientUuid(): string {
  const c = typeof crypto !== "undefined" ? crypto : undefined;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === "function") {
    c.getRandomValues(bytes);
  } else {
    const seed = `${Date.now()}-${++idempotencyCounter}`;
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = (seed.charCodeAt(index % seed.length) + index * 31) & 0xff;
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
