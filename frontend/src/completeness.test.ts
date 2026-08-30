/**
 * 档案完整度 TS 镜像测试。
 * 夹具与 tests/unit/profile/test_completeness.py 一致：
 * 两侧断言相同分数（跨语言同步契约），改任何一侧要同步另一侧。
 */
import { describe, expect, it } from 'vitest';
import { profileCompleteness } from './completeness';
import type { Profile } from './api/types';

const MINIMAL = {
  id: 'p1',
  label: '最小档案',
  basic: { name: '张三', phone: '13800000000', email: 'z@example.com' },
} as Partial<Profile>;

const FULL = {
  id: 'p2',
  label: '完整档案',
  basic: {
    name: '张三',
    phone: '13800000000',
    email: 'z@example.com',
    gender: '男',
    birth_date: { year: 2000, month: 1 },
    political_status: '共青团员',
    current_city: '成都市',
    native_place: '四川',
  },
  intention: { position: '算法工程师', city: ['成都'], salary_expectation: '20-30K' },
  education: [
    {
      school: '示例大学',
      college: '计算机学院',
      major: '计算机',
      degree: '本科',
      gpa: '3.5',
      period: { start: { year: 2019, month: 9 } },
    },
  ],
  experiences: [
    { kind: 'internship', organization: '示例公司', period: { start: { year: 2023, month: 3 } } },
    { kind: 'project', organization: '实验室', period: { start: { year: 2022, month: 9 } } },
  ],
  skills: ['Python'],
  certificates: ['CET-6'],
  self_evaluation: '踏实肯干',
  extended: { origin_place: '四川' },
  attachments: [{ kind: 'resume', label: '中文简历', path: 'C:/x.pdf' }],
} as Partial<Profile>;

describe('profileCompleteness（与后端 Python 镜像同步）', () => {
  it('最小档案 15 分，缺失教育/附件', () => {
    const { score, missing } = profileCompleteness(MINIMAL);
    expect(score).toBe(15);
    expect(missing).toContain('教育经历');
    expect(missing).toContain('默认简历附件');
    expect(missing).not.toContain('学院');
  });

  it('完整档案 100 分无缺失', () => {
    const { score, missing } = profileCompleteness(FULL);
    expect(score).toBe(100);
    expect(missing).toEqual([]);
  });
});
