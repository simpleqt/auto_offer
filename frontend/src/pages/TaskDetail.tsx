import { useEffect, useMemo, useRef } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Popconfirm,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, CopyOutlined } from '@ant-design/icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getTask } from '../api/client';
import type { FieldStatus, TaskOut } from '../api/types';
import { useTaskStream } from '../api/ws';
import {
  ACTIVE_TASK_STATES,
  FIELD_STATUS_COLORS,
  FIELD_STATUS_LABELS,
  TASK_STATE_COLORS,
  TASK_STATE_LABELS,
} from '../constants';
import { fmtTime } from '../profile-utils';

export default function TaskDetail({
  taskId,
  onResume,
  onCancel,
  onChanged,
}: {
  taskId: string;
  onResume: () => void;
  onCancel: () => void;
  onChanged: () => void;
}) {
  const qc = useQueryClient();
  const { events, connState, liveState } = useTaskStream(taskId);
  const listRef = useRef<HTMLDivElement>(null);

  // 从实时流推断当前状态，用于决定是否继续轮询详情。
  const liveStateValue = liveState?.type === 'state' ? liveState.value : undefined;
  const { data: task } = useQuery({
    queryKey: ['task', taskId],
    queryFn: () => getTask(taskId),
    refetchInterval: (query) => {
      const s = liveStateValue ?? query.state.data?.state;
      return s && ACTIVE_TASK_STATES.has(s) ? 3000 : false;
    },
  });

  // 实时流状态变化时同步刷新任务详情（如任务转 AWAITING_REVIEW 后取回报告）。
  useEffect(() => {
    if (liveStateValue) qc.invalidateQueries({ queryKey: ['task', taskId] });
  }, [liveStateValue, taskId, qc]);

  // 有活跃任务时周期性刷新任务列表
  useEffect(() => {
    if (!task || !ACTIVE_TASK_STATES.has(task.state)) return;
    const timer = setInterval(() => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      onChanged();
    }, 3000);
    return () => clearInterval(timer);
  }, [task, qc, onChanged]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [events.length]);

  const state = liveStateValue ?? task?.state;
  const waitReason =
    liveState?.type === 'state' && liveState.reason ? liveState.reason : task?.wait_reason;

  const stepEvents = useMemo(() => events.filter((e) => e.type === 'step'), [events]);

  function copyEvents() {
    if (stepEvents.length === 0) {
      message.info('暂无动作流水可复制');
      return;
    }
    const text = stepEvents.map((e) => `[${e.seq}] ${e.agent}: ${e.summary}`).join('\n');
    navigator.clipboard
      .writeText(text)
      .then(() => message.success('动作流水已复制'))
      .catch(() => {
        // 非 https 或剪贴板受限时兜底
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand('copy');
          message.success('动作流水已复制');
        } catch {
          message.error('复制失败，请手动选择文本');
        } finally {
          document.body.removeChild(ta);
        }
      });
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <Typography.Text strong>任务详情</Typography.Text>
            {state && <Tag color={TASK_STATE_COLORS[state]}>{TASK_STATE_LABELS[state]}</Tag>}
            <Badge
              status={
                connState === 'open'
                  ? 'processing'
                  : connState === 'connecting'
                    ? 'default'
                    : 'error'
              }
              text={connState === 'open' ? '实时' : connState}
            />
          </Space>
        }
        extra={
          <Space>
            {state === 'WAITING_HUMAN' && (
              <Button type="primary" icon={<CheckCircleOutlined />} onClick={onResume}>
                人工处理完成，继续
              </Button>
            )}
            {state && ACTIVE_TASK_STATES.has(state) && state !== 'WAITING_HUMAN' && (
              <Popconfirm title="取消该任务？" onConfirm={onCancel}>
                <Button danger icon={<CloseCircleOutlined />}>
                  取消
                </Button>
              </Popconfirm>
            )}
          </Space>
        }
      >
        {task && (
          <Descriptions column={2} size="small">
            <Descriptions.Item label="URL" span={2}>
              <Typography.Text copyable>{task.url}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="页面标题">{task.page_title || '—'}</Descriptions.Item>
            <Descriptions.Item label="创建时间">{fmtTime(task.created_at)}</Descriptions.Item>
          </Descriptions>
        )}
        {state === 'WAITING_HUMAN' && waitReason && (
          <Typography.Paragraph type="warning" style={{ marginTop: 12 }}>
            需要人工处理：{waitReason}
          </Typography.Paragraph>
        )}
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Card
            title="动作流水"
            extra={
              <Button size="small" icon={<CopyOutlined />} onClick={copyEvents}>
                复制
              </Button>
            }
            styles={{ body: { height: 360, overflow: 'auto' } }}
          >
            <div ref={listRef}>
              <Timeline
                items={stepEvents.map((e) => ({
                  color:
                    e.agent === 'validator' ? 'blue' : e.agent === 'planner' ? 'purple' : 'green',
                  children: (
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        [{e.seq}] {e.agent}
                      </Typography.Text>
                      <div style={{ fontSize: 13 }}>{e.summary}</div>
                    </div>
                  ),
                }))}
              />
              {stepEvents.length === 0 && (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无事件" />
              )}
            </div>
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card title="填写报告">
            {task?.report ? (
              <ReportView report={task.report} />
            ) : (
              <Empty description="任务完成后生成报告" />
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

function ReportView({ report }: { report: NonNullable<TaskOut['report']> }) {
  const counts = useMemo(() => {
    const c = { filled: 0, failed: 0, skipped: 0, pending_confirm: 0 };
    for (const f of report.fields) c[f.status] += 1;
    return c;
  }, [report.fields]);

  return (
    <div>
      <Row gutter={8} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <Statistic title="已填写" value={counts.filled} valueStyle={{ color: '#52c41a' }} />
        </Col>
        <Col span={6}>
          <Statistic title="失败" value={counts.failed} valueStyle={{ color: '#ff4d4f' }} />
        </Col>
        <Col span={6}>
          <Statistic title="跳过" value={counts.skipped} />
        </Col>
        <Col span={6}>
          <Statistic
            title="待确认"
            value={counts.pending_confirm}
            valueStyle={{ color: '#faad14' }}
          />
        </Col>
      </Row>
      <Typography.Text type="secondary">
        LLM 调用 {report.total_llm_calls} 次 · tokens {report.total_tokens}
      </Typography.Text>
      <Table
        size="small"
        rowKey={(r) => `${r.label}-${r.status}`}
        pagination={false}
        dataSource={report.fields}
        columns={[
          {
            title: '字段',
            dataIndex: 'label',
            render: (v, r) => (
              <Space>
                {v}
                {r.sensitive && <Tag color="orange">敏感</Tag>}
              </Space>
            ),
          },
          {
            title: '状态',
            dataIndex: 'status',
            render: (s: FieldStatus) => (
              <Tag color={FIELD_STATUS_COLORS[s]}>{FIELD_STATUS_LABELS[s]}</Tag>
            ),
          },
          { title: '值', dataIndex: 'value', ellipsis: true },
          { title: '说明', dataIndex: 'note', ellipsis: true },
        ]}
      />
    </div>
  );
}
