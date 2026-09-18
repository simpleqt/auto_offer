/**
 * 任务事件 WebSocket Hook：连接 /ws/tasks/{task_id}，
 * 服务端先回放历史事件再推送实时事件，本 Hook 归一为统一的 WsEvent 列表。
 *
 * 断线自动重连（指数退避）；重连后服务端会重新回放历史，按 seq 去重
 * 防止重复入列；seq 出现跳号视为缺口（断线期间丢事件或超出服务端
 * 保留上限），latched 到 hasGap 供界面提示时间线可能不完整。
 */
import { useEffect, useRef, useState } from 'react';
import type { WsEvent } from './types';

export type ConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error';

const MAX_EVENTS = 2000;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;
const RECONNECT_MAX_ATTEMPTS = 10;

function wsUrl(taskId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/tasks/${encodeURIComponent(taskId)}`;
}

export function useTaskStream(taskId: string | null) {
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [connState, setConnState] = useState<ConnectionState>('connecting');
  const [liveState, setLiveState] = useState<WsEvent | null>(null);
  const [hasGap, setHasGap] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const lastSeqRef = useRef(0);
  const disposedRef = useRef(false);
  const retryRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!taskId) {
      setEvents([]);
      setConnState('closed');
      setLiveState(null);
      setHasGap(false);
      return;
    }

    disposedRef.current = false;
    retryRef.current = 0;
    lastSeqRef.current = 0;
    setEvents([]);
    setLiveState(null);
    setHasGap(false);
    setConnState('connecting');

    const handleMessage = (data: string) => {
      let parsed: WsEvent;
      try {
        parsed = JSON.parse(data) as WsEvent;
      } catch {
        return;
      }
      if (parsed.type === 'ping') return;
      const seq = Number((parsed as { seq?: number }).seq ?? 0);
      // seq>0 的事件按序号去重与测缺；state 固定 seq=0 不参与
      if (seq > 0) {
        if (seq <= lastSeqRef.current) return; // 重连回放已见过的
        if (lastSeqRef.current > 0 && seq > lastSeqRef.current + 1) setHasGap(true);
        lastSeqRef.current = seq;
      }
      setEvents((prev) => {
        const next = [...prev, parsed];
        return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
      });
      if (parsed.type === 'state' || parsed.type === 'report') setLiveState(parsed);
    };

    const scheduleReconnect = () => {
      if (disposedRef.current) return;
      if (retryRef.current >= RECONNECT_MAX_ATTEMPTS) {
        setConnState('closed');
        return;
      }
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** retryRef.current, RECONNECT_MAX_MS);
      retryRef.current += 1;
      setConnState('reconnecting');
      timerRef.current = window.setTimeout(connect, delay);
    };

    const connect = () => {
      if (disposedRef.current) return;
      setConnState(retryRef.current > 0 ? 'reconnecting' : 'connecting');
      const ws = new WebSocket(wsUrl(taskId));
      wsRef.current = ws;
      ws.onopen = () => {
        retryRef.current = 0;
        setConnState('open');
      };
      ws.onmessage = (ev) => handleMessage(ev.data as string);
      ws.onerror = () => setConnState('error');
      ws.onclose = scheduleReconnect;
    };
    connect();

    return () => {
      disposedRef.current = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [taskId]);

  return { events, connState, liveState, hasGap };
}
