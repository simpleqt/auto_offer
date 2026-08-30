/**
 * 档案完整度评分（0-100 + 缺失项清单）。
 *
 * 与后端 core/autooffer_core/profile/completeness.py 逻辑镜像：
 * 两侧测试用同一份夹具断言相同分数，修改任何一侧时同步另一侧。
 * 输入是表单值形状（日期可为 Dayjs，仅做真值判断，不影响结果）。
 */
import type { Profile } from './api/types';

export interface CompletenessResult {
  score: number;
  missing: string[];
}

export function profileCompleteness(p: Partial<Profile>): CompletenessResult {
  let score = 0;
  const missing: string[] = [];
  const check = (value: unknown, weight: number, label: string) => {
    if (value) score += weight;
    else missing.push(label);
  };

  const b: Partial<Profile['basic']> = p.basic ?? {};
  check(b.name, 5, '姓名');
  check(b.phone, 5, '手机号');
  check(b.email, 5, '邮箱');
  check(b.gender, 2, '性别');
  check(b.birth_date, 2, '出生日期');
  check(b.political_status, 2, '政治面貌');
  check(b.current_city, 2, '现居住城市');
  check(b.native_place, 2, '籍贯');

  const edu = p.education?.[0];
  if (p.education?.length) {
    score += 10;
    check(edu?.college, 3, '学院');
    check(edu?.major, 3, '专业');
    check(edu?.degree, 2, '学历');
    check(edu?.gpa, 2, '成绩/GPA');
  } else {
    missing.push('教育经历');
  }

  const it = p.intention;
  if (it) {
    check(it.position, 5, '意向岗位');
    check(it.city?.length, 3, '期望城市');
    check(it.salary_expectation, 2, '期望薪资');
  } else {
    missing.push('意向岗位', '期望城市', '期望薪资');
  }

  const exp = p.experiences ?? [];
  check(
    exp.some((x) => x.kind === 'internship' || x.kind === 'work'),
    10,
    '实习/工作经历',
  );
  check(
    exp.some((x) => x.kind === 'project'),
    10,
    '项目经历',
  );

  check(p.skills?.length, 4, '专业技能');
  check(p.certificates?.length, 3, '证书');
  check(p.self_evaluation, 3, '自我评价');

  const ext = p.extended;
  check(
    ext &&
      (ext.origin_place ||
        ext.hukou_location ||
        ext.marital_status ||
        ext.travel_willingness ||
        ext.relocation_willingness ||
        ext.available_date ||
        ext.party_join_date ||
        ext.personality ||
        ext.languages?.length ||
        ext.awards?.length ||
        ext.campus_roles?.length ||
        ext.references?.length),
    5,
    '扩展信息（婚姻/户口/获奖等）',
  );

  check(
    (p.attachments ?? []).some((a) => a.kind === 'resume'),
    10,
    '默认简历附件',
  );

  return { score, missing };
}
