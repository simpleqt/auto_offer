import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import OnboardingPage from './OnboardingPage';
import { renderWithProviders } from '../test/renderWithProviders';

// mock api/client：只测组件的向导步骤逻辑，不依赖真实后端
vi.mock('../api/client', () => ({
  listModels: vi.fn(),
  listProfiles: vi.fn(),
}));

import { listModels, listProfiles } from '../api/client';

const listModelsMock = listModels as ReturnType<typeof vi.fn>;
const listProfilesMock = listProfiles as ReturnType<typeof vi.fn>;

describe('OnboardingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('无模型无档案时停留在第一步，引导去配置模型', async () => {
    listModelsMock.mockResolvedValue([]);
    listProfilesMock.mockResolvedValue([]);
    renderWithProviders(<OnboardingPage goTo={() => {}} />);

    expect(await screen.findByText('先配置一个模型端点')).toBeInTheDocument();
    expect(screen.getByText('去配置模型')).toBeInTheDocument();
  });

  it('有模型无档案时进入第二步，引导去建立档案', async () => {
    listModelsMock.mockResolvedValue([{ id: 'ep1' }]);
    listProfilesMock.mockResolvedValue([]);
    renderWithProviders(<OnboardingPage goTo={() => {}} />);

    expect(await screen.findByText('再建立你的个人档案')).toBeInTheDocument();
    expect(screen.getByText('去建立档案')).toBeInTheDocument();
  });

  it('模型与档案齐备时进入第三步，显示准备就绪', async () => {
    listModelsMock.mockResolvedValue([{ id: 'ep1' }]);
    listProfilesMock.mockResolvedValue([{ id: 'p1' }]);
    renderWithProviders(<OnboardingPage goTo={() => {}} />);

    expect(await screen.findByText('准备就绪')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '发起任务' })).toBeInTheDocument();
  });
});
