import { useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  List,
  Row,
  Select,
  Space,
  Steps,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { listTaskEvents, listTasks } from '../api/client';
import type { AgentEvent, TaskOut } from '../api/types';
import { TASK_STATE_COLORS, TASK_STATE_LABELS } from '../constants';
import { fmtTime } from '../profile-utils';

export default function ReplayPage() {
  const { data: tasks } = useQuery({ queryKey: ['tasks'], queryFn: () => listTasks(50) });
  const [taskId, setTaskId] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);

  const { data: events, isLoading } = useQuery({
    queryKey: ['events', taskId],
    queryFn: () => listTaskEvents(taskId!, 500),
    enabled: !!taskId,
  });

  const task = tasks?.find((t) => t.id === taskId);
  const stepEvents = useMemo(
    () => (events ?? []).filter((e) => e.kind === 'step' || e.kind === 'state'),
    [events],
  );
  const current = stepEvents[cursor];

  return (
    <Row gutter={16}>
      <Col span={8}>
        <Card title="选择任务">
          <Select
            style={{ width: '100%' }}
            placeholder="选择一个任务回放"
            value={taskId ?? undefined}
            onChange={(v) => {
              setTaskId(v);
              setCursor(0);
            }}
            options={(tasks ?? []).map((t) => ({
              value: t.id,
              label: `${t.id} · ${TASK_STATE_LABELS[t.state]}`,
            }))}
          />
          {task && (
            <Descriptions column={1} size="small" style={{ marginTop: 12 }}>
              <Descriptions.Item label="URL">
                <Typography.Text copyable style={{ fontSize: 12 }}>{task.url}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={TASK_STATE_COLORS[task.state]}>{TASK_STATE_LABELS[task.state]}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="创建">{fmtTime(task.created_at)}</Descriptions.Item>
            </Descriptions>
          )}
        </Card>
      </Col>
      <Col span={16}>
        <Card
          title="审计回放"
          extra={
            <Space>
              <Button
                icon={<LeftOutlined />}
                disabled={cursor === 0}
                onClick={() => setCursor((c) => Math.max(0, c - 1))}
              />
              <Typography.Text>
                {stepEvents.length ? `${cursor + 1} / ${stepEvents.length}` : '0 / 0'}
              </Typography.Text>
              <Button
                icon={<RightOutlined />}
                disabled={cursor >= stepEvents.length - 1}
                onClick={() => setCursor((c) => Math.min(stepEvents.length - 1, c + 1))}
              />
            </Space>
          }
        >
          {isLoading ? (
            <Empty description="加载中…" />
          ) : !current ? (
            <Empty description="暂无事件" />
          ) : (
            <Space direction="vertical" style={{ width: '100%' }} size={16}>
              <Card size="small" title={`第 ${current.seq} 步 · ${current.agent || '—'}`}>
                <Typography.Text>{current.summary}</Typography.Text>
                {Object.keys(current.data ?? {}).length > 0 && (
                  <pre style={{ marginTop: 12, fontSize: 12, background: '#fafafa', padding: 8, overflow: 'auto' }}>
                    {JSON.stringify(current.data, null, 2)}
                  </pre>
                )}
              </Card>
              <Steps
                size="small"
                current={cursor}
                items={stepEvents.map((e) => ({ title: `${e.seq} ${e.agent}` }))}
                responsive
              />
              <Typography.Text type="secondary">
                时间：{fmtTime(current.created_at)}
              </Typography.Text>
            </Space>
          )}
        </Card>
      </Col>
    </Row>
  );
}
