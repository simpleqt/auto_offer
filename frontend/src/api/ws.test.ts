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
    ws.onopen?.();

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

  it('断线后按退避重连，重连回放的重复 seq 不再入列', () => {
    const { result } = renderHook(() => useTaskStream('task-1'));
    // effect 在 renderHook 的 act 内同步执行，无需 waitFor
    expect(FakeWebSocket.instances.length).toBe(1);
    const first = FakeWebSocket.instances[0];
    first.onopen?.();
    act(() => {
      first.emit({ type: 'step', seq: 1, agent: 'actor', summary: '第一条' });
      first.emit({ type: 'step', seq: 2, agent: 'actor', summary: '第二条' });
    });

    // 假定时器只在重连调度阶段启用（waitFor 与假定时器不兼容，避免使用）
    vi.useFakeTimers();
    try {
      act(() => {
        first.close(); // 服务重启等场景
      });
      expect(result.current.connState).toBe('reconnecting');

      act(() => {
        vi.advanceTimersByTime(1000); // 首次退避 1s
      });
      expect(FakeWebSocket.instances.length).toBe(2);
      const second = FakeWebSocket.instances[1];
      act(() => {
        second.onopen?.();
      });
      expect(result.current.connState).toBe('open');

      // 重连后服务端回放历史：seq 1/2 已见过，只有新事件入列
      act(() => {
        second.emit({ type: 'step', seq: 1, agent: 'actor', summary: '回放-第一条' });
        second.emit({ type: 'step', seq: 3, agent: 'actor', summary: '新事件' });
      });
      const steps = result.current.events.filter((e) => e.type === 'step');
      expect(steps).toHaveLength(3);
      expect(result.current.hasGap).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('seq 跳号 latched 到 hasGap（断线丢事件/超出保留上限）', async () => {
    const { result } = renderHook(() => useTaskStream('task-1'));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    ws.onopen?.();

    act(() => {
      ws.emit({ type: 'step', seq: 5, agent: 'actor', summary: '首条（回放截尾后从5开始）' });
    });
    // 首条之前 lastSeq=0 不算缺口；之后跳号才算
    expect(result.current.hasGap).toBe(false);

    act(() => {
      ws.emit({ type: 'step', seq: 9, agent: 'actor', summary: '跳号' });
    });
    expect(result.current.hasGap).toBe(true);
  });

  it('事件列表有上限，超出保留最新一段', async () => {
    const { result } = renderHook(() => useTaskStream('task-1'));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    ws.onopen?.();

    act(() => {
      for (let i = 1; i <= 2100; i += 1) {
        ws.emit({ type: 'step', seq: i, agent: 'actor', summary: `事件${i}` });
      }
    });
    const steps = result.current.events.filter((e) => e.type === 'step');
    expect(steps).toHaveLength(2000);
    expect(steps[0]).toMatchObject({ seq: 101 });
    expect(steps[steps.length - 1]).toMatchObject({ seq: 2100 });
  });

  it('卸载后不再重连（清理定时器并停止重试）', () => {
    vi.useFakeTimers();
    try {
      const { unmount } = renderHook(() => useTaskStream('task-1'));
      expect(FakeWebSocket.instances.length).toBe(1);
      const ws = FakeWebSocket.instances[0];
      ws.onopen?.();
      unmount();

      act(() => {
        vi.advanceTimersByTime(60000);
      });
      expect(FakeWebSocket.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
