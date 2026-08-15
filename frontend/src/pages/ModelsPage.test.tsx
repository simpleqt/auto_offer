import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import ModelsPage from './ModelsPage';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../api/client', () => ({
  listModels: vi.fn(),
  getRouting: vi.fn(),
  putRouting: vi.fn(),
  upsertModel: vi.fn(),
  deleteModel: vi.fn(),
  probeModel: vi.fn(),
}));

import { getRouting, listModels } from '../api/client';

const listModelsMock = listModels as ReturnType<typeof vi.fn>;
const getRoutingMock = getRouting as ReturnType<typeof vi.fn>;

describe('ModelsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('渲染端点名称与默认徽标', async () => {
    listModelsMock.mockResolvedValue([
      {
        id: 'ep1',
        name: '本地 Qwen',
        base_url: 'http://127.0.0.1:8011/v1',
        model: 'qwen3.5-35b',
        key_hint: 'sk-***1234',
        temperature: 0.1,
        max_tokens: 4096,
        timeout_s: 600,
        max_concurrency: 4,
        extra_body: {},
        supports_vision: null,
        is_default: true,
      },
    ]);
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
});
