import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProfilesPage from './ProfilesPage';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../api/client', () => ({
  listProfiles: vi.fn(),
  getProfile: vi.fn(),
  deleteProfile: vi.fn(),
  parseResume: vi.fn(),
  putProfile: vi.fn(),
}));

import { getProfile, listProfiles } from '../api/client';

const listProfilesMock = listProfiles as ReturnType<typeof vi.fn>;
const getProfileMock = getProfile as ReturnType<typeof vi.fn>;

const SAMPLE_PROFILE = {
  id: 'p1',
  label: '中文-算法岗',
  basic: {
    name: '张三',
    gender: null,
    birth_date: null,
    phone: '13800001111',
    email: 'zhangsan@example.com',
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
  extended: null,
  qa_bank: [],
  attachments: [],
};

describe('ProfilesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('空档案列表时展示引导文案', async () => {
    listProfilesMock.mockResolvedValue([]);

    renderWithProviders(<ProfilesPage />);

    expect(await screen.findByText(/从左侧选择一个档案/)).toBeInTheDocument();
  });

  it('渲染档案列表与附件数', async () => {
    listProfilesMock.mockResolvedValue([
      {
        id: 'p1',
        label: '中文-算法岗',
        updated_at: '2026-08-15T10:00:00',
        name: '张三',
        attachments: 2,
      },
    ]);

    renderWithProviders(<ProfilesPage />);

    expect(await screen.findByText('中文-算法岗')).toBeInTheDocument();
    expect(await screen.findByText('2 附件')).toBeInTheDocument();
  });

  it('选中档案后编辑器渲染解析出的个人信息（回归：getProfile 直接返回 Profile）', async () => {
    listProfilesMock.mockResolvedValue([
      {
        id: 'p1',
        label: '中文-算法岗',
        updated_at: '2026-08-15T10:00:00',
        name: '张三',
        attachments: 0,
      },
    ]);
    getProfileMock.mockResolvedValue(SAMPLE_PROFILE);

    renderWithProviders(<ProfilesPage />);
    await screen.findByText('中文-算法岗');

    // 点击左侧档案列表项
    await userEvent.click(screen.getByText('中文-算法岗'));

    // 编辑器应回填姓名 / 电话 / 邮箱（证明 payload 结构被正确解析）
    expect(await screen.findByDisplayValue('张三')).toBeInTheDocument();
    expect(screen.getByDisplayValue('13800001111')).toBeInTheDocument();
    expect(screen.getByDisplayValue('zhangsan@example.com')).toBeInTheDocument();
  });
});
