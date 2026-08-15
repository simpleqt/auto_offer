/**
 * 轻量 REST 客户端：统一拼装 base path、JSON 序列化、错误归一。
 * 仅使用浏览器原生 fetch，无额外依赖。
 */

import type {
  ApplicationRecord,
  ApplicationStatusIn,
  EndpointIn,
  EndpointOut,
  FillReport,
  HealthInfo,
  ParseResumeResult,
  Profile,
  ProfileListRow,
  ProfileSummary,
  ProbeResult,
  RoleRouting,
  TaskIn,
  TaskOut,
  AgentEvent,
  UsageReport,
} from './types';

const BASE = '/api/v1';

/** 后端返回的统一错误：FastAPI 默认 { detail: string }。 */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const hasJsonBody = init?.body != null && !(init.body instanceof FormData);
  const res = await fetch(`${BASE}${path}`, {
    headers: hasJsonBody ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === 'string') detail = body.detail;
      else if (body?.detail) detail = JSON.stringify(body.detail);
    } catch {
      /* 忽略非 JSON 响应体 */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------- 系统 ----------

export const health = () => request<HealthInfo>('/system/health');
export const version = () => request<{ version: string }>('/system/version');
export const usageReport = () => request<UsageReport>('/usage');

// ---------- 模型端点 ----------

export const listModels = () => request<EndpointOut[]>('/models');
export const upsertModel = (body: EndpointIn) =>
  request<EndpointOut>('/models', { method: 'PUT', body: JSON.stringify(body) });
export const deleteModel = (id: string) =>
  request<{ deleted: boolean }>(`/models/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const probeModel = (id: string) =>
  request<ProbeResult>(`/models/${encodeURIComponent(id)}/probe`, { method: 'POST' });
export const getRouting = () => request<RoleRouting>('/models/routing');
export const putRouting = (mapping: RoleRouting) =>
  request<RoleRouting>('/models/routing', { method: 'PUT', body: JSON.stringify({ mapping }) });

// ---------- 档案 ----------

export const listProfiles = () => request<ProfileSummary[]>('/profiles');
export const getProfile = (id: string) =>
  request<ProfileListRow>(`/profiles/${encodeURIComponent(id)}`);
export const putProfile = (id: string, payload: Profile) =>
  request<Profile>(`/profiles/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify({ payload }),
  });
export const deleteProfile = (id: string) =>
  request<{ deleted: boolean }>(`/profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const parseResume = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return request<ParseResumeResult>('/profiles/parse-resume', { method: 'POST', body: form });
};

// ---------- 任务 ----------

export const createTask = (body: TaskIn) =>
  request<TaskOut>('/tasks', { method: 'POST', body: JSON.stringify(body) });
export const listTasks = (limit = 50) => request<TaskOut[]>(`/tasks?limit=${limit}`);
export const getTask = (id: string) => request<TaskOut>(`/tasks/${encodeURIComponent(id)}`);
export const resumeTask = (id: string) =>
  request<{ resumed: boolean }>(`/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST' });
export const cancelTask = (id: string) =>
  request<{ cancelled: boolean }>(`/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
export const listTaskEvents = (id: string, limit = 500) =>
  request<AgentEvent[]>(`/tasks/${encodeURIComponent(id)}/events?limit=${limit}`);

// ---------- 投递列表 ----------

export const listApplications = (status?: string) =>
  request<ApplicationRecord[]>(status ? `/applications?status=${status}` : '/applications');
export const updateApplication = (id: string, body: ApplicationStatusIn) =>
  request<ApplicationRecord>(`/applications/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
export const deleteApplication = (id: string) =>
  request<{ deleted: boolean }>(`/applications/${encodeURIComponent(id)}`, { method: 'DELETE' });

export type { FillReport };
