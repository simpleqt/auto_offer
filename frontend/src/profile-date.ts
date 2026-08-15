/**
 * 档案表单的日期类型转换工具。
 *
 * 后端 Profile 用 {year, month?, day?}（DateYM）表示日期；
 * antd DatePicker 用 Dayjs 对象。这里提供两者间的递归双向转换，
 * 使整个 Profile 结构可作为 Form 的 initialValues 直接使用。
 */
import dayjs from 'dayjs';
import type { DateYM } from './api/types';

/** 判断一个对象是否是 DateYM 形状（{year, month?, day?}）。 */
function isDateYM(v: unknown): v is DateYM {
  if (v == null || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return typeof o.year === 'number' && ('month' in o || 'day' in o);
}

/** 递归把 Profile 中的 DateYM 结构转换为 antd DatePicker 需要的 Dayjs。 */
export function datesToDayjs<T>(value: T): T {
  if (Array.isArray(value)) return value.map(datesToDayjs) as unknown as T;
  if (isDateYM(value)) {
    return dayjs(
      `${value.year}-${String(value.month ?? 1).padStart(2, '0')}-${String(value.day ?? 1).padStart(2, '0')}`,
    ) as unknown as T;
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = datesToDayjs(v);
    }
    return out as unknown as T;
  }
  return value;
}

/** 递归把 Form 值中的 Dayjs 转回后端 DateYM 结构。 */
export function dayjsToDates<T>(value: T): T {
  if (Array.isArray(value)) return value.map(dayjsToDates) as unknown as T;
  if (dayjs.isDayjs(value)) {
    return { year: value.year(), month: value.month() + 1, day: value.date() } as unknown as T;
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = dayjsToDates(v);
    }
    return out as unknown as T;
  }
  return value;
}
