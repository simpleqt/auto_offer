import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useTaskStream } from './ws';

/**
 * 用可控的假 WebSocket 验证事件归一与历史回放行为。
 * 服务端在连接建立后先回放历史事件，再推送实时事件。
 */
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN_EVENT: () => void = () => {};

  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.onclose?.();
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe('useTaskStream', () => {
  const originalWebSocket = globalThis.WebSocket;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    // @ts-expect-error 注入可控假 WebSocket
    globalThis.WebSocket = FakeWebSocket;
  });

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket;
    vi.restoreAllMocks();
  });

  it('taskId 为空时状态为 closed 且无事件', () => {
    const { result } = renderHook(() => useTaskStream(null));
    expect(result.current.connState).toBe('closed');
    expect(result.current.events).toEqual([]);
  });

  it('收到 state 事件后更新 liveState', async () => {
    const { result } = renderHook(() => useTaskStream('task-1'));

    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    ws.onopen?.();

    act(() => {
      ws.emit({ type: 'state', value: 'RUNNING', reason: '' });
    });

    expect(result.current.connState).toBe('open');
    expect(result.current.liveState).toMatchObject({ type: 'state', value: 'RUNNING' });
  });

  it('累积 step 事件，忽略 ping', async () => {
    const { result } = renderHook(() => useTaskStream('task-1'));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];

    act(() => {
      ws.emit({ type: 'step', seq: 1, agent: 'planner', summary: '拆分' });
      ws.emit({ type: 'ping' });
      ws.emit({ type: 'step', seq: 2, agent: 'actor', summary: '填写' });
    });

    expect(result.current.events).toHaveLength(2);
    const [first, second] = result.current.events;
    if (first.type !== 'step' || second.type !== 'step') {
      throw new Error('预期两条 step 事件');
    }
    expect(first.seq).toBe(1);
    expect(second.seq).toBe(2);
  });
});
