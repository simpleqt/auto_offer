import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import SettingsPage from './SettingsPage';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../api/client', () => ({
  getSettings: vi.fn(),
  putSettings: vi.fn(),
  health: vi.fn(),
}));

import { getSettings, health } from '../api/client';

const getSettingsMock = getSettings as ReturnType<typeof vi.fn>;
const healthMock = health as ReturnType<typeof vi.fn>;

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getSettingsMock.mockResolvedValue({
      browser_mode: 'managed',
      cdp_endpoint: '',
      minimize_on_startup: false,
    });
    healthMock.mockResolvedValue({
      status: 'ok',
      version: '0.1.0',
      data_dir: 'C:/Users/x/AppData/Roaming/AutoOffer',
      headless: false,
    });
  });

  it('默认显示「软件自控浏览器」模式', async () => {
    renderWithProviders(<SettingsPage />);
    expect(await screen.findByText('浏览器连接方式')).toBeInTheDocument();
    expect(screen.getByLabelText('软件自控浏览器（推荐）')).toBeChecked();
  });

  it('切换到 CDP 模式后显示远程调试地址输入框', async () => {
    renderWithProviders(<SettingsPage />);
    await screen.findByText('浏览器连接方式');

    // 选择「我日常用的 Chrome / Edge」
    const cdpRadio = screen.getByLabelText('我日常用的 Chrome / Edge');
    await import('@testing-library/user-event').then(({ default: userEvent }) =>
      userEvent.click(cdpRadio),
    );

    expect(await screen.findByLabelText('浏览器远程调试地址（CDP）')).toBeInTheDocument();
    expect(screen.getByText(/如何开启调试端口/)).toBeInTheDocument();
  });
});
