/**
 * 与后端契约一一对应的 TypeScript 类型。
 * 来源：server/autooffer_server/api/schemas.py、core/autooffer_core/profile/schema.py、
 *       core/autooffer_core/report.py、core/autooffer_core/applications.py。
 * 注意：后端 api_key 只入不出，响应中恒为 key_hint 掩码。
 */

// ---------- 模型端点 ----------

export interface EndpointIn {
  id: string;
  name?: string;
  base_url: string;
  model: string;
  /** 新增/更新时传入；不回显。留空表示保留原有 key。 */
  api_key?: string | null;
  temperature?: number;
  max_tokens?: number;
  timeout_s?: number;
  max_concurrency?: number;
  extra_body?: Record<string, unknown>;
  is_default?: boolean;
}

export interface EndpointOut {
  id: string;
  name: string;
  base_url: string;
  model: string;
  key_hint: string;
  temperature: number;
  max_tokens: number;
  timeout_s: number;
  max_concurrency: number;
  extra_body: Record<string, unknown>;
  supports_vision: boolean | null;
  is_default: boolean;
}

export interface ProbeResult {
  reachable: boolean;
  supports_vision: boolean | null;
  available_models: string[];
  latency_ms: number;
  error: string | null;
}

// ---------- 档案 ----------

export type DateYM = { year: number; month: number | null; day: number | null };
export type DateRange = { start: DateYM; end: DateYM | null };

export type Degree = '高中' | '大专' | '本科' | '硕士' | '博士' | '其他';
export type ExperienceKind = 'internship' | 'work' | 'project';
export type AttachmentKind =
  'resume' | 'photo' | 'transcript' | 'certificate' | 'portfolio' | 'other';
export type AttachmentLanguage = 'zh' | 'en';

export interface Education {
  school: string;
  major: string | null;
  degree: Degree | null;
  period: DateRange;
  gpa: string | null;
  description: string | null;
}

export interface Experience {
  kind: ExperienceKind;
  organization: string;
  title: string | null;
  period: DateRange;
  description: string | null;
  highlights: string[];
}

export interface BasicInfo {
  name: string;
  gender: '男' | '女' | '其他' | null;
  birth_date: DateYM | null;
  phone: string;
  email: string;
  native_place: string | null;
  current_city: string | null;
  political_status: string | null;
  /** restricted 级：命中时需界面单独授权。 */
  id_number: string | null;
}

export interface JobIntention {
  position: string | null;
  city: string[];
  salary_expectation: string | null;
  available_date: DateYM | null;
}

export interface QAPair {
  question: string;
  answer: string;
}

export interface LanguageSkill {
  language: string;
  level: string | null;
  score: string | null;
  certificate_date: DateYM | null;
}

export interface Award {
  title: string;
  level: string | null;
  date: DateYM | null;
  description: string | null;
}

export interface CampusRole {
  organization: string;
  role: string;
  period: DateRange | null;
  description: string | null;
}

export interface FamilyMember {
  relation: string;
  name: string;
  workplace: string | null;
  title: string | null;
  phone: string | null;
}

export interface Reference {
  name: string;
  relation: string;
  organization: string | null;
  title: string | null;
  phone: string | null;
  email: string | null;
}

export interface PersonalityInfo {
  traits: string[];
  mbti: string | null;
  assessment_summary: string | null;
  hobbies: string[];
  specialties: string[];
}

export interface ExtendedInfo {
  personality: PersonalityInfo | null;
  languages: LanguageSkill[];
  awards: Award[];
  campus_roles: CampusRole[];
  family_members: FamilyMember[];
  emergency_contact: FamilyMember | null;
  marital_status: string | null;
  height_cm: number | null;
  weight_kg: number | null;
  health_status: string | null;
  party_join_date: DateYM | null;
  hukou_location: string | null;
  origin_place: string | null;
  references: Reference[];
  links: Record<string, string>;
  available_date: DateYM | null;
  travel_willingness: string | null;
  relocation_willingness: string | null;
}

export interface Attachment {
  kind: AttachmentKind;
  label: string;
  path: string;
  language: AttachmentLanguage | null;
  meta: Record<string, string | number>;
}

export interface Profile {
  id: string;
  label: string;
  basic: BasicInfo;
  intention: JobIntention | null;
  education: Education[];
  experiences: Experience[];
  skills: string[];
  certificates: string[];
  self_evaluation: string | null;
  extended: ExtendedInfo | null;
  qa_bank: QAPair[];
  attachments: Attachment[];
}

export interface ProfileSummary {
  id: string;
  label: string;
  updated_at: string;
  name: string;
  attachments: number;
}

// ---------- 任务 ----------

export type TaskState =
  'QUEUED' | 'RUNNING' | 'WAITING_HUMAN' | 'AWAITING_REVIEW' | 'DONE' | 'FAILED' | 'CANCELLED';

export type FieldStatus = 'filled' | 'failed' | 'skipped' | 'pending_confirm';

export interface FieldRecord {
  label: string;
  status: FieldStatus;
  value: string | null;
  attempts: number;
  note: string | null;
  sensitive: boolean;
}

export interface FillReport {
  task_id: string;
  url: string;
  page_title: string;
  profile_id: string;
  fields: FieldRecord[];
  started_at: string;
  finished_at: string;
  total_llm_calls: number;
  total_tokens: number;
  note: string | null;
}

export interface TaskIn {
  url: string;
  profile_id: string;
  options?: Record<string, unknown>;
}

export interface TaskOut {
  id: string;
  url: string;
  profile_id: string;
  state: TaskState;
  page_title: string;
  wait_reason: string;
  report: FillReport | null;
  created_at: string;
  updated_at: string;
}

// ---------- 审计事件 ----------

export interface AgentEvent {
  seq: number;
  kind: string;
  agent: string;
  summary: string;
  data: Record<string, unknown>;
  created_at?: string;
}

// ---------- 投递列表 ----------

export type ApplicationStatus = 'filled' | 'submitted' | 'interview' | 'rejected' | 'abandoned';

export interface ApplicationRecord {
  id: string;
  url: string;
  company: string;
  position: string;
  profile_id: string;
  status: ApplicationStatus;
  filled_at: string;
  updated_at: string;
  fields_filled: number;
  fields_failed: number;
  fields_pending: number;
  note: string | null;
}

export interface ApplicationStatusIn {
  status: ApplicationStatus;
  note?: string | null;
}

// ---------- 系统 ----------

export interface HealthInfo {
  status: string;
  version: string;
  data_dir: string;
  headless: boolean;
}

export interface ParseResumeResult {
  profile: Profile;
  low_confidence_paths: string[];
}

// ---------- 模型调用统计（FR-M5） ----------

export interface UsageAggregate {
  calls: number;
  failed: number;
  failure_rate: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  avg_latency_ms: number;
}

export interface ModelUsage extends UsageAggregate {
  model: string;
}

export interface TaskUsage extends UsageAggregate {
  task_id: string;
}

export interface UsageReport {
  by_model: ModelUsage[];
  by_task: TaskUsage[];
}

// ---------- 应用设置 ----------

export type BrowserMode = 'managed' | 'cdp';

export interface AppSettings {
  browser_mode: BrowserMode;
  cdp_endpoint: string;
  minimize_on_startup: boolean;
}

// ---------- WebSocket 事件 ----------

export type WsEvent =
  | { type: 'step'; seq: number; agent: string; summary: string; data: Record<string, unknown> }
  | { type: 'state'; value: TaskState; reason: string }
  | { type: 'report'; data: Record<string, unknown> }
  | { type: 'ping' };

/** 角色路由：role -> endpoint_id。 */
export type RoleRouting = Record<string, string>;
