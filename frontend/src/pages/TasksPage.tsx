import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Empty,
  Form,
  Input,
  List,
  message,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Timeline,
  Typography,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  cancelTask,
  createTask,
  getTask,
  listProfiles,
  listTasks,
  resumeTask,
} from '../api/client';
import type { FieldStatus, TaskOut, WsEvent } from '../api/types';
import { useTaskStream } from '../api/ws';
import {
  FIELD_STATUS_COLORS,
  FIELD_STATUS_LABELS,
  TASK_STATE_COLORS,
  TASK_STATE_LABELS,
} from '../constants';
import { fmtTime } from '../profile-utils';

const ACTIVE_STATES = new Set(['QUEUED', 'RUNNING', 'WAITING_HUMAN', 'AWAITING_REVIEW']);

export default function TasksPage() {
  const qc = useQueryClient();
  const { data: tasks, isLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => listTasks(50),
    refetchInterval: 3000,
  });
  const { data: profiles } = useQuery({ queryKey: ['profiles'], queryFn: listProfiles });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form] = Form.useForm();

  const create = useMutation({
    mutationFn: (body: { url: string; profile_id: string }) => createTask(body),
    onSuccess: (t) => {
      message.success('任务已创建');
      qc.invalidateQueries({ queryKey: ['tasks'] });
      setSelectedId(t.id);
      form.resetFields();
    },
    onError: (e: Error) => message.error(e.message),
  });

  const resume = useMutation({
    mutationFn: (id: string) => resumeTask(id),
    onSuccess: () => {
      message.success('已继续');
      qc.invalidateQueries({ queryKey: ['tasks'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const cancel = useMutation({
    mutationFn: (id: string) => cancelTask(id),
    onSuccess: () => {
      message.success('已取消');
      qc.invalidateQueries({ queryKey: ['tasks'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  return (
    <Row gutter={16}>
      <Col span={8}>
        <Card title="新建任务" style={{ marginBottom: 16 }}>
          <Form
            form={form}
            layout="vertical"
            onFinish={(v) => create.mutate(v)}
          >
            <Form.Item name="url" label="目标表单 URL" rules={[{ required: true, type: 'url', message: '请输入合法 URL' }]}>
              <Input.TextArea rows={3} placeholder="https://example.com/apply" />
            </Form.Item>
            <Form.Item name="profile_id" label="使用档案" rules={[{ required: true, message: '请选择档案' }]}>
              <Select
                placeholder="选择档案"
                options={(profiles ?? []).map((p) => ({ value: p.id, label: p.label || p.name || p.id }))}
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" icon={<PlayCircleOutlined />} loading={create.isPending} block>
              开始填写
            </Button>
          </Form>
        </Card>

        <Card title="任务列表" extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => qc.invalidateQueries({ queryKey: ['tasks'] })} />}>
          {isLoading ? (
            <Spin />
          ) : (tasks?.length ?? 0) === 0 ? (
            <Empty description="暂无任务" />
          ) : (
            <List
              dataSource={tasks}
              renderItem={(t) => (
                <List.Item
                  style={{ cursor: 'pointer', background: t.id === selectedId ? '#f0f5ff' : undefined }}
                  onClick={() => setSelectedId(t.id)}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <Tag color={TASK_STATE_COLORS[t.state]}>{TASK_STATE_LABELS[t.state]}</Tag>
                        <Typography.Text style={{ fontSize: 13 }}>{t.id}</Typography.Text>
                      </Space>
                    }
                    description={
                      <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                        {t.page_title || t.url}
                      </Typography.Text>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      </Col>

      <Col span={16}>
        {selectedId ? (
          <TaskDetail
            key={selectedId}
            taskId={selectedId}
            onResume={() => resume.mutate(selectedId)}
            onCancel={() => cancel.mutate(selectedId)}
            onChanged={() => qc.invalidateQueries({ queryKey: ['tasks'] })}
          />
        ) : (
          <Card><Empty description="从左侧选择任务查看实时进度" /></Card>
        )}
      </Col>
    </Row>
  );
}

function TaskDetail({
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
      return s && ACTIVE_STATES.has(s) ? 3000 : false;
    },
  });

  // 实时流状态变化时同步刷新任务详情（如任务转 AWAITING_REVIEW 后取回报告）。
  useEffect(() => {
    if (liveStateValue) qc.invalidateQueries({ queryKey: ['task', taskId] });
  }, [liveStateValue, taskId, qc]);

  // 有活跃任务时周期性刷新任务列表
  useEffect(() => {
    if (!task || !ACTIVE_STATES.has(task.state)) return;
    const timer = setInterval(() => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      onChanged();
    }, 3000);
    return () => clearInterval(timer);
  }, [task?.state, qc, onChanged]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [events.length]);

  const state = liveStateValue ?? task?.state;
  const waitReason =
    liveState?.type === 'state' && liveState.reason ? liveState.reason : task?.wait_reason;

  const stepEvents = useMemo(() => events.filter((e) => e.type === 'step'), [events]);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <Typography.Text strong>任务详情</Typography.Text>
            {state && <Tag color={TASK_STATE_COLORS[state]}>{TASK_STATE_LABELS[state]}</Tag>}
            <Badge
              status={
                connState === 'open' ? 'processing' : connState === 'connecting' ? 'default' : 'error'
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
            {ACTIVE_STATES.has(state ?? '') && state !== 'WAITING_HUMAN' && (
              <Popconfirm title="取消该任务？" onConfirm={onCancel}>
                <Button danger icon={<CloseCircleOutlined />}>取消</Button>
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

      <Row gutter={16}>
        <Col span={12}>
          <Card title="动作流水" styles={{ body: { height: 360, overflow: 'auto' } }}>
            <div ref={listRef}>
              <Timeline
                items={stepEvents.map((e) => ({
                  color: e.agent === 'validator' ? 'blue' : e.agent === 'planner' ? 'purple' : 'green',
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
              {stepEvents.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无事件" />}
            </div>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="填写报告">
            {task?.report ? <ReportView report={task.report} /> : <Empty description="任务完成后生成报告" />}
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
        <Col span={6}><Statistic title="已填写" value={counts.filled} valueStyle={{ color: '#52c41a' }} /></Col>
        <Col span={6}><Statistic title="失败" value={counts.failed} valueStyle={{ color: '#ff4d4f' }} /></Col>
        <Col span={6}><Statistic title="跳过" value={counts.skipped} /></Col>
        <Col span={6}><Statistic title="待确认" value={counts.pending_confirm} valueStyle={{ color: '#faad14' }} /></Col>
      </Row>
      <Typography.Text type="secondary">LLM 调用 {report.total_llm_calls} 次 · tokens {report.total_tokens}</Typography.Text>
      <Table
        size="small"
        rowKey={(r) => `${r.label}-${r.status}`}
        pagination={false}
        dataSource={report.fields}
        columns={[
          { title: '字段', dataIndex: 'label', render: (v, r) => (
            <Space>
              {v}
              {r.sensitive && <Tag color="orange">敏感</Tag>}
            </Space>
          ) },
          { title: '状态', dataIndex: 'status', render: (s: FieldStatus) => <Tag color={FIELD_STATUS_COLORS[s]}>{FIELD_STATUS_LABELS[s]}</Tag> },
          { title: '值', dataIndex: 'value', ellipsis: true },
          { title: '说明', dataIndex: 'note', ellipsis: true },
        ]}
      />
    </div>
  );
}
