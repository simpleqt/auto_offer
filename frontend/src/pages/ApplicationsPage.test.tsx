import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import ApplicationsPage from './ApplicationsPage';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../api/client', () => ({
  listApplications: vi.fn(),
  updateApplication: vi.fn(),
  deleteApplication: vi.fn(),
}));

import { listApplications } from '../api/client';

const listApplicationsMock = listApplications as ReturnType<typeof vi.fn>;

describe('ApplicationsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('渲染投递记录的公司与岗位', async () => {
    listApplicationsMock.mockResolvedValue([
      {
        id: 'app-1',
        url: 'https://example.com/apply',
        company: '星辰科技',
        position: '算法工程师',
        profile_id: 'p1',
        status: 'filled',
        filled_at: '2026-08-15T10:00:00',
        updated_at: '2026-08-15T10:00:00',
        fields_filled: 3,
        fields_failed: 0,
        fields_pending: 1,
        note: null,
      },
    ]);

    renderWithProviders(<ApplicationsPage />);

    expect(await screen.findByText('星辰科技')).toBeInTheDocument();
    expect(screen.getByText('算法工程师')).toBeInTheDocument();
  });

  it('空列表时表格无数据且不崩溃', async () => {
    listApplicationsMock.mockResolvedValue([]);
    renderWithProviders(<ApplicationsPage />);

    // 标题始终存在
    expect(await screen.findByText('投递列表')).toBeInTheDocument();
  });
});
