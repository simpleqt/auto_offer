/**
 * 任务事件 WebSocket Hook：连接 /ws/tasks/{task_id}，
 * 服务端先回放历史事件再推送实时事件，本 Hook 归一为统一的 WsEvent 列表。
 */
import { useEffect, useRef, useState } from 'react';
import type { WsEvent } from './types';

export type ConnectionState = 'connecting' | 'open' | 'closed' | 'error';

function wsUrl(taskId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/tasks/${encodeURIComponent(taskId)}`;
}

export function useTaskStream(taskId: string | null) {
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [connState, setConnState] = useState<ConnectionState>('connecting');
  const [liveState, setLiveState] = useState<WsEvent | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!taskId) {
      setEvents([]);
      setConnState('closed');
      setLiveState(null);
      return;
    }

    setEvents([]);
    setLiveState(null);
    setConnState('connecting');
    const ws = new WebSocket(wsUrl(taskId));
    wsRef.current = ws;

    ws.onopen = () => setConnState('open');
    ws.onmessage = (ev) => {
      let parsed: WsEvent;
      try {
        parsed = JSON.parse(ev.data as string) as WsEvent;
      } catch {
        return;
      }
      if (parsed.type === 'ping') return;
      setEvents((prev) => [...prev, parsed]);
      if (parsed.type === 'state' || parsed.type === 'report') setLiveState(parsed);
    };
    ws.onerror = () => setConnState('error');
    ws.onclose = () => setConnState('closed');

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [taskId]);

  return { events, connState, liveState };
}
