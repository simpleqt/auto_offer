import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, health, parseResume, upsertModel } from './client';

describe('api client', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch as typeof fetch;
    vi.restoreAllMocks();
  });

  function mockFetch(status: number, body: unknown) {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    });
  }

  it('GET 请求拼装 /api/v1 前缀且不带 Content-Type', async () => {
    mockFetch(200, { status: 'ok' });
    const result = await health();
    expect(result).toEqual({ status: 'ok' });
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('/api/v1/system/health');
    expect(init?.headers).toBeUndefined();
  });

  it('PUT JSON 请求带 Content-Type 头与序列化 body', async () => {
    mockFetch(200, { id: 'ep1' });
    await upsertModel({ id: 'ep1', base_url: 'http://x/v1', model: 'm', api_key: 'sk-1' });
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('/api/v1/models');
    expect(init?.method).toBe('PUT');
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' });
    expect(JSON.parse(init!.body as string)).toMatchObject({ id: 'ep1', base_url: 'http://x/v1' });
  });

  it('FormData 请求（简历解析）不覆盖 Content-Type', async () => {
    mockFetch(200, { profile: {}, low_confidence_paths: [] });
    const file = new File(['resume'], 'resume.pdf', { type: 'application/pdf' });
    await parseResume(file);
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('/api/v1/profiles/parse-resume');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBeInstanceOf(FormData);
    // 交给浏览器自动设置 multipart 边界，客户端不应手动指定 Content-Type
    expect(init?.headers).toBeUndefined();
  });

  it('非 2xx 响应抛出带 detail 的 ApiError', async () => {
    mockFetch(422, { detail: '档案校验失败: xxx' });
    await expect(upsertModel({ id: 'x', base_url: 'u', model: 'm' })).rejects.toThrow(
      ApiError,
    );
    await expect(upsertModel({ id: 'x', base_url: 'u', model: 'm' })).rejects.toMatchObject({
      status: 422,
      message: '档案校验失败: xxx',
    });
  });

  it('非 JSON 错误响应体也能抛出 HTTP 错误', async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error('not json');
      },
    });
    await expect(health()).rejects.toThrow('HTTP 500');
  });
});
