/** 前端共享常量与展示映射。 */

import type { ApplicationStatus, FieldStatus, TaskState } from './api/types';

export const AGENT_ROLES = ['planner', 'actor', 'validator', 'profile_parser', 'writer'] as const;
export type AgentRole = (typeof AGENT_ROLES)[number];

export const ROLE_LABELS: Record<AgentRole, string> = {
  planner: '规划（Planner）',
  actor: '执行（Actor）',
  validator: '校验（Validator）',
  profile_parser: '简历解析',
  writer: '文案生成',
};

export const TASK_STATE_LABELS: Record<TaskState, string> = {
  QUEUED: '排队中',
  RUNNING: '运行中',
  WAITING_HUMAN: '等待人工',
  AWAITING_REVIEW: '等待审核',
  DONE: '已完成',
  FAILED: '失败',
  CANCELLED: '已取消',
};

export const TASK_STATE_COLORS: Record<TaskState, string> = {
  QUEUED: 'default',
  RUNNING: 'processing',
  WAITING_HUMAN: 'warning',
  AWAITING_REVIEW: 'purple',
  DONE: 'success',
  FAILED: 'error',
  CANCELLED: 'default',
};

export const FIELD_STATUS_LABELS: Record<FieldStatus, string> = {
  filled: '已填写',
  failed: '失败',
  skipped: '跳过',
  pending_confirm: '待确认',
};

export const FIELD_STATUS_COLORS: Record<FieldStatus, string> = {
  filled: 'success',
  failed: 'error',
  skipped: 'default',
  pending_confirm: 'warning',
};

export const APP_STATUS_LABELS: Record<ApplicationStatus, string> = {
  filled: '已填写',
  submitted: '已提交',
  interview: '面试中',
  rejected: '已拒',
  abandoned: '放弃',
};

export const APP_STATUS_COLORS: Record<ApplicationStatus, string> = {
  filled: 'blue',
  submitted: 'green',
  interview: 'gold',
  rejected: 'red',
  abandoned: 'default',
};

export const ATTACHMENT_KIND_LABELS: Record<string, string> = {
  resume: '简历',
  photo: '证件照',
  transcript: '成绩单',
  certificate: '证书',
  portfolio: '作品集',
  other: '其他',
};

export const EXPERIENCE_KIND_LABELS: Record<string, string> = {
  internship: '实习经历',
  work: '工作经历',
  project: '项目经历',
};

export const DEGREE_OPTIONS = ['高中', '大专', '本科', '硕士', '博士', '其他'];
export const GENDER_OPTIONS = ['男', '女', '其他'];
