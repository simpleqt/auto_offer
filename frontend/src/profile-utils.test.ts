import { describe, expect, it } from 'vitest';
import { emptyProfile, fmtTime, newProfileId } from './profile-utils';

describe('profile-utils', () => {
  it('emptyProfile 生成结构完整的空档案', () => {
    const p = emptyProfile('p1');
    expect(p.id).toBe('p1');
    expect(p.basic.name).toBe('');
    expect(p.basic.phone).toBe('');
    expect(p.basic.email).toBe('');
    expect(p.education).toEqual([]);
    expect(p.experiences).toEqual([]);
    expect(p.extended).not.toBeNull();
    expect(p.extended?.languages).toEqual([]);
    expect(p.qa_bank).toEqual([]);
    expect(p.attachments).toEqual([]);
  });

  it('emptyProfile 每次返回独立的扩展信息对象（避免共享引用）', () => {
    const a = emptyProfile('a');
    const b = emptyProfile('b');
    a.extended!.languages.push({ language: '英语', level: null, score: null, certificate_date: null });
    expect(b.extended!.languages).toEqual([]);
  });

  it('newProfileId 生成非空且格式合规的 id', () => {
    const id = newProfileId();
    expect(id).toMatch(/^p-/);
    expect(id.length).toBeGreaterThan(2);
  });

  it('newProfileId 连续生成不重复', () => {
    const seen = new Set<string>();
    for (let i = 0; i < 1000; i++) seen.add(newProfileId());
    expect(seen.size).toBe(1000);
  });

  it('fmtTime 空值返回占位符', () => {
    expect(fmtTime(null)).toBe('—');
    expect(fmtTime(undefined)).toBe('—');
    expect(fmtTime('')).toBe('—');
  });

  it('fmtTime 合法 ISO 时间转本地可读字符串', () => {
    const out = fmtTime('2026-08-15T12:34:56');
    expect(out).toContain('2026');
    expect(out).not.toBe('2026-08-15T12:34:56');
  });

  it('fmtTime 非法时间返回原串（不抛异常）', () => {
    expect(fmtTime('not-a-date')).toBe('not-a-date');
  });
});
