/** 档案编辑相关的工厂与工具。 */

import type { ExtendedInfo, Profile } from './api/types';

export function emptyExtended(): ExtendedInfo {
  return {
    personality: null,
    languages: [],
    awards: [],
    campus_roles: [],
    family_members: [],
    emergency_contact: null,
    marital_status: null,
    height_cm: null,
    weight_kg: null,
    health_status: null,
    party_join_date: null,
    hukou_location: null,
    origin_place: null,
    references: [],
    links: {},
    available_date: null,
    travel_willingness: null,
    relocation_willingness: null,
  };
}

export function emptyProfile(id = ''): Profile {
  return {
    id,
    label: '',
    basic: {
      name: '',
      gender: null,
      birth_date: null,
      phone: '',
      email: '',
      native_place: null,
      current_city: null,
      political_status: null,
      id_number: null,
    },
    intention: null,
    education: [],
    experiences: [],
    skills: [],
    certificates: [],
    self_evaluation: null,
    extended: emptyExtended(),
    qa_bank: [],
    attachments: [],
  };
}

export function newProfileId(): string {
  return `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** 时间戳转本地可读字符串（后端返回 ISO 秒级）。 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
