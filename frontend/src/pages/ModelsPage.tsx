import { useMemo, useState } from 'react';
import {
  Button,
  Card,
  Col,
  Drawer,
  Form,
  Input,
  InputNumber,
  message,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import { DeleteOutlined, EditOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  deleteModel,
  getRouting,
  listModels,
  probeModel,
  putRouting,
  upsertModel,
  usageReport,
} from '../api/client';
import type { EndpointIn, EndpointOut, ProbeResult, RoleRouting } from '../api/types';
import { ROLE_LABELS } from '../constants';

export default function ModelsPage() {
  const qc = useQueryClient();
  const { data: models, isLoading } = useQuery({ queryKey: ['models'], queryFn: listModels });
  const { data: routing } = useQuery({ queryKey: ['routing'], queryFn: getRouting });
  const { data: usage } = useQuery({ queryKey: ['usage'], queryFn: usageReport });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editing, setEditing] = useState<EndpointOut | null>(null);
  const [probeResults, setProbeResults] = useState<Record<string, ProbeResult>>({});
  const [probing, setProbing] = useState<string | null>(null);
  const [form] = Form.useForm();

  const upsert = useMutation({
    mutationFn: (body: EndpointIn) => upsertModel(body),
    onSuccess: () => {
      message.success('已保存端点');
      setDrawerOpen(false);
      qc.invalidateQueries({ queryKey: ['models'] });
      qc.invalidateQueries({ queryKey: ['routing'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteModel(id),
    onSuccess: () => {
      message.success('已删除');
      qc.invalidateQueries({ queryKey: ['models'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const saveRouting = useMutation({
    mutationFn: (mapping: RoleRouting) => putRouting(mapping),
    onSuccess: () => {
      message.success('角色路由已更新');
      qc.invalidateQueries({ queryKey: ['routing'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  async function handleProbe(id: string) {
    setProbing(id);
    try {
      const r = await probeModel(id);
      setProbeResults((prev) => ({ ...prev, [id]: r }));
      qc.invalidateQueries({ queryKey: ['models'] });
      if (r.reachable) message.success('连通正常');
      else message.warning(r.error || '探测失败');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setProbing(null);
    }
  }

  function openCreate() {
    setEditing(null);
    form.resetFields();
    setDrawerOpen(true);
  }

  function openEdit(ep: EndpointOut) {
    setEditing(ep);
    form.setFieldsValue({
      ...ep,
      api_key: '',
      extra_body: JSON.stringify(ep.extra_body ?? {}),
    });
    setDrawerOpen(true);
  }

  const routingMap = useMemo<Record<string, string>>(() => routing ?? {}, [routing]);

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (v: string, r: EndpointOut) => (
        <Space>
          <Typography.Text strong>{v || r.id}</Typography.Text>
          {r.is_default && <Tag color="blue">默认</Tag>}
        </Space>
      ),
    },
    { title: '模型', dataIndex: 'model' },
    { title: 'Base URL', dataIndex: 'base_url', ellipsis: true },
    {
      title: 'Key',
      dataIndex: 'key_hint',
      render: (v: string) => <Typography.Text code>{v || '—'}</Typography.Text>,
    },
    {
      title: '连通性',
      dataIndex: 'id',
      render: (id: string) => {
        const pr = probeResults[id];
        const vision = models?.find((m) => m.id === id)?.supports_vision;
        if (!pr && vision == null) return <Tag>未探测</Tag>;
        const reachable = pr ? pr.reachable : true;
        return (
          <Space>
            <Tag color={reachable ? 'green' : 'red'}>{reachable ? '连通' : '失败'}</Tag>
            {pr?.reachable && pr.latency_ms != null && (
              <Tag color={pr.latency_ms < 1500 ? 'cyan' : 'orange'}>{pr.latency_ms}ms</Tag>
            )}
            {vision != null && (
              <Tag color={vision ? 'geekblue' : 'default'}>{vision ? '视觉' : '纯文本'}</Tag>
            )}
          </Space>
        );
      },
    },
    {
      title: '操作',
      dataIndex: 'id',
      render: (id: string, r: EndpointOut) => (
        <Space>
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={probing === id}
            onClick={() => handleProbe(id)}
          >
            探测
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>
            编辑
          </Button>
          <Popconfirm title="删除该端点？" onConfirm={() => remove.mutate(id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card
          title="模型端点"
          extra={
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              添加端点
            </Button>
          }
        >
          {isLoading ? (
            <Spin />
          ) : models && models.length === 0 ? (
            <Typography.Paragraph type="secondary">
              尚未配置模型端点。点击「添加端点」填入你的 OpenAI 兼容端点（base_url / api_key /
              模型名）， 软件会一键测试连通性与视觉能力。
            </Typography.Paragraph>
          ) : (
            <Table rowKey="id" columns={columns} dataSource={models} pagination={false} />
          )}
        </Card>

        <Card
          title="角色路由"
          extra={<Typography.Text type="secondary">未配置的角色回落默认端点</Typography.Text>}
        >
          <Row gutter={[16, 16]}>
            {(Object.keys(ROLE_LABELS) as (keyof typeof ROLE_LABELS)[]).map((role) => (
              <Col xs={24} sm={12} xl={8} key={role}>
                <Space wrap>
                  <Typography.Text style={{ minWidth: 130, display: 'inline-block' }}>
                    {ROLE_LABELS[role]}
                  </Typography.Text>
                  <Select
                    style={{ minWidth: 200 }}
                    allowClear
                    placeholder="默认端点"
                    value={routingMap[role]}
                    options={(models ?? []).map((m) => ({ value: m.id, label: m.name || m.id }))}
                    onChange={(v) => saveRouting.mutate({ ...routingMap, [role]: v ?? '' })}
                  />
                </Space>
              </Col>
            ))}
          </Row>
        </Card>

        <Card
          title="模型调用统计"
          extra={
            <Typography.Text type="secondary">
              按模型聚合 token 用量 / 时延 / 失败率
            </Typography.Text>
          }
        >
          <Table
            rowKey="model"
            size="small"
            pagination={false}
            dataSource={usage?.by_model ?? []}
            locale={{ emptyText: '暂无调用记录（发起任务后自动统计）' }}
            columns={[
              { title: '模型', dataIndex: 'model' },
              { title: '调用次数', dataIndex: 'calls' },
              {
                title: '失败',
                dataIndex: 'failed',
                render: (v: number) => (
                  <Typography.Text type={v > 0 ? 'danger' : undefined}>{v}</Typography.Text>
                ),
              },
              {
                title: '失败率',
                dataIndex: 'failure_rate',
                render: (v: number) => `${(v * 100).toFixed(1)}%`,
              },
              {
                title: 'Tokens',
                dataIndex: 'total_tokens',
                render: (v: number) => v.toLocaleString(),
              },
              {
                title: '平均时延',
                dataIndex: 'avg_latency_ms',
                render: (v: number) => `${v} ms`,
              },
            ]}
          />
        </Card>
      </Space>

      <Drawer
        title={editing ? '编辑端点' : '添加端点'}
        width={480}
        open={drawerOpen}
        forceRender
        onClose={() => setDrawerOpen(false)}
        extra={
          <Button type="primary" loading={upsert.isPending} onClick={() => form.submit()}>
            保存
          </Button>
        }
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ temperature: 0.1, max_tokens: 4096, timeout_s: 600, max_concurrency: 4 }}
          onFinish={(vals) => {
            const id = editing ? editing.id : `ep-${Date.now().toString(36)}`;
            let extraBody: Record<string, unknown> = {};
            if (vals.extra_body) {
              try {
                extraBody = JSON.parse(vals.extra_body) as Record<string, unknown>;
              } catch {
                message.error('extra_body 不是合法 JSON，请检查后重试');
                return;
              }
            }
            upsert.mutate({
              ...vals,
              id,
              api_key: vals.api_key || null,
              is_default: !!vals.is_default,
              extra_body: extraBody,
            });
          }}
        >
          <Form.Item name="name" label="显示名称">
            <Input placeholder="如 Qwen3.5-35B（自建 vLLM）" />
          </Form.Item>
          <Form.Item name="base_url" label="Base URL" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="http://127.0.0.1:8011/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" extra="留空表示保留原有 key（编辑时）。">
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item name="model" label="模型名" rules={[{ required: true, message: '必填' }]}>
            <Input placeholder="qwen3.5-35b" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="temperature" label="Temperature">
                <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="max_tokens" label="Max Tokens">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="timeout_s" label="超时（秒）">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="max_concurrency" label="并发上限">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="extra_body" label="extra_body（JSON）">
            <Input.TextArea
              rows={3}
              placeholder='{"chat_template_kwargs": {"enable_thinking": false}}'
            />
          </Form.Item>
          <Form.Item name="is_default" label="设为默认端点" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
