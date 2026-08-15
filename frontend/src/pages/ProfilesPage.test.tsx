import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import ProfilesPage from './ProfilesPage';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../api/client', () => ({
  listProfiles: vi.fn(),
  getProfile: vi.fn(),
  deleteProfile: vi.fn(),
  parseResume: vi.fn(),
  putProfile: vi.fn(),
}));

import { listProfiles } from '../api/client';

const listProfilesMock = listProfiles as ReturnType<typeof vi.fn>;

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
});
