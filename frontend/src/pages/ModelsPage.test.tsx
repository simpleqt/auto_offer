import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ModelsPage from './ModelsPage';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../api/client', () => ({
  listModels: vi.fn(),
  getRouting: vi.fn(),
  putRouting: vi.fn(),
  upsertModel: vi.fn(),
  deleteModel: vi.fn(),
  probeModel: vi.fn(),
  usageReport: vi.fn(),
}));

import { getRouting, listModels, usageReport } from '../api/client';

const listModelsMock = listModels as ReturnType<typeof vi.fn>;
const getRoutingMock = getRouting as ReturnType<typeof vi.fn>;
const usageReportMock = usageReport as ReturnType<typeof vi.fn>;

const ENDPOINT = {
  id: 'ep1',
  name: '本地 Qwen',
  base_url: 'http://127.0.0.1:8011/v1',
  model: 'qwen3.5-35b',
  key_hint: 'sk-***1234',
  temperature: 0.1,
  max_tokens: 4096,
  timeout_s: 600,
  max_concurrency: 4,
  extra_body: { chat_template_kwargs: { enable_thinking: false } },
  supports_vision: null,
  is_default: true,
};

describe('ModelsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usageReportMock.mockResolvedValue({ by_model: [], by_task: [] });
  });

  it('渲染端点名称与默认徽标', async () => {
    listModelsMock.mockResolvedValue([ENDPOINT]);
    getRoutingMock.mockResolvedValue({});

    renderWithProviders(<ModelsPage />);

    expect(await screen.findByText('本地 Qwen')).toBeInTheDocument();
    expect(screen.getByText('qwen3.5-35b')).toBeInTheDocument();
    expect(screen.getByText('默认')).toBeInTheDocument();
  });

  it('空端点列表时展示引导文案', async () => {
    listModelsMock.mockResolvedValue([]);
    getRoutingMock.mockResolvedValue({});

    renderWithProviders(<ModelsPage />);

    expect(await screen.findByText(/尚未配置模型端点/)).toBeInTheDocument();
  });

  it('编辑端点时 extra_body 以 JSON 字符串回填（可保存）', async () => {
    listModelsMock.mockResolvedValue([ENDPOINT]);
    getRoutingMock.mockResolvedValue({});

    renderWithProviders(<ModelsPage />);
    await screen.findByText('本地 Qwen');

    // 打开编辑抽屉
    await userEvent.click(screen.getByRole('button', { name: /编辑/ }));

    // TextArea 应显示 JSON 字符串，而不是 [object Object]
    const textarea = await screen.findByPlaceholderText(
      '{"chat_template_kwargs": {"enable_thinking": false}}',
    );
    expect(textarea).toHaveValue(
      JSON.stringify({ chat_template_kwargs: { enable_thinking: false } }),
    );

    // 编辑抽屉标题为「编辑端点」
    expect(await screen.findByText('编辑端点')).toBeInTheDocument();
  });
});
