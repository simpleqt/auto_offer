import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  message,
  Popconfirm,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import { DeleteOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { deleteApplication, listApplications, updateApplication } from '../api/client';
import type { ApplicationRecord, ApplicationStatus } from '../api/types';
import { APP_STATUS_COLORS, APP_STATUS_LABELS } from '../constants';
import { fmtTime } from '../profile-utils';

const STATUS_OPTIONS = Object.keys(APP_STATUS_LABELS) as ApplicationStatus[];

/** 投递看板：总数、状态分布、近 7 天投递趋势（纯 CSS 条形，不引图表库）。 */
function Dashboard({ rows }: { rows: ApplicationRecord[] }) {
  const total = rows.length;
  const counts = STATUS_OPTIONS.map((s) => ({
    status: s,
    n: rows.filter((r) => r.status === s).length,
  })).filter((c) => c.n > 0);

  const days: { label: string; n: number }[] = [];
  const today = new Date();
  for (let i = 6; i >= 0; i -= 1) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const key = `${d.getMonth() + 1}/${d.getDate()}`;
    const n = rows.filter((r) => {
      const rd = new Date(r.filled_at);
      return (
        rd.getFullYear() === d.getFullYear() &&
        rd.getMonth() === d.getMonth() &&
        rd.getDate() === d.getDate()
      );
    }).length;
    days.push({ label: key, n });
  }
  const maxDay = Math.max(1, ...days.map((d) => d.n));

  return (
    <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
      <Col xs={8} md={5}>
        <Statistic title="累计投递" value={total} />
      </Col>
      <Col xs={16} md={9}>
        <div style={{ fontSize: 12, color: 'var(--ao-text-3, #888)', marginBottom: 6 }}>
          状态分布
        </div>
        <Space size={6} wrap>
          {counts.length === 0 && <Typography.Text type="secondary">暂无</Typography.Text>}
          {counts.map((c) => (
            <Tag key={c.status} color={APP_STATUS_COLORS[c.status]}>
              {APP_STATUS_LABELS[c.status]} {c.n}
            </Tag>
          ))}
        </Space>
      </Col>
      <Col xs={24} md={10}>
        <div style={{ fontSize: 12, color: 'var(--ao-text-3, #888)', marginBottom: 6 }}>
          近 7 天
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 56 }}>
          {days.map((d) => (
            <div
              key={d.label}
              title={`${d.label}：${d.n} 次`}
              style={{
                flex: 1,
                height: `${Math.max(6, (d.n / maxDay) * 100)}%`,
                background: 'var(--ao-selected, #2e5be6)',
                opacity: d.n > 0 ? 0.85 : 0.25,
                borderRadius: 3,
                minHeight: 4,
              }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 2 }}>
          {days.map((d, i) => (
            <Typography.Text
              key={d.label}
              type="secondary"
              style={{ flex: 1, fontSize: 10, textAlign: 'center' }}
            >
              {i === 3 ? d.label : d.label.split('/')[1]}
            </Typography.Text>
          ))}
        </div>
      </Col>
    </Row>
  );
}

/** 状态色点：Select 收起态与下拉项统一带色，扫一眼即可分辨投递阶段。 */
function statusDot(color: string) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: color,
        flex: 'none',
      }}
    />
  );
}

function urlHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export default function ApplicationsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<ApplicationStatus | undefined>();
  const { data, isLoading } = useQuery({
    queryKey: ['applications', filter],
    queryFn: () => listApplications(filter),
  });
  // 看板基于全量数据（列表可能带状态过滤）
  const { data: all } = useQuery({
    queryKey: ['applications', undefined],
    queryFn: () => listApplications(undefined),
  });

  const update = useMutation({
    mutationFn: ({ id, status, note }: { id: string; status: ApplicationStatus; note?: string }) =>
      updateApplication(id, { status, note }),
    onSuccess: (_d, vars) => {
      // 备注保存与状态更新区分提示，让用户知道备注已被持久化
      message.success(vars.note !== undefined ? '备注已保存' : '状态已更新');
      qc.invalidateQueries({ queryKey: ['applications'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteApplication(id),
    onSuccess: () => {
      message.success('已删除');
      qc.invalidateQueries({ queryKey: ['applications'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const columns = [
    {
      title: '公司',
      dataIndex: 'company',
      render: (v: string, r: ApplicationRecord) =>
        v ? (
          <a href={r.url} target="_blank" rel="noreferrer">
            {v}
          </a>
        ) : (
          <a href={r.url} target="_blank" rel="noreferrer" style={{ opacity: 0.65 }}>
            {urlHost(r.url) || '待补'}
          </a>
        ),
    },
    {
      title: '岗位',
      dataIndex: 'position',
      render: (v: string) => v || <Typography.Text type="secondary">待补</Typography.Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (s: ApplicationStatus, r: ApplicationRecord) => (
        <Select
          size="small"
          value={s}
          style={{ width: 110 }}
          options={STATUS_OPTIONS.map((v) => ({
            value: v,
            label: (
              <Space size={6}>
                {statusDot(APP_STATUS_COLORS[v])}
                {APP_STATUS_LABELS[v]}
              </Space>
            ),
          }))}
          onChange={(v) => update.mutate({ id: r.id, status: v })}
        />
      ),
    },
    {
      title: '填写统计',
      render: (_: unknown, r: ApplicationRecord) => (
        <Space size={4}>
          <Tag color="green">{r.fields_filled} 成功</Tag>
          <Tag color="red">{r.fields_failed} 失败</Tag>
          <Tag color="orange">{r.fields_pending} 待确认</Tag>
        </Space>
      ),
    },
    { title: '填写时间', dataIndex: 'filled_at', render: (v: string) => fmtTime(v) },
    {
      title: '备注',
      dataIndex: 'note',
      render: (_: unknown, r: ApplicationRecord) => (
        <Input
          size="small"
          placeholder="备注（失焦或回车保存）"
          defaultValue={r.note ?? ''}
          onPressEnter={(e) => (e.target as HTMLInputElement).blur()}
          onBlur={(e) => {
            const v = e.target.value.trim();
            if (v !== (r.note ?? '')) update.mutate({ id: r.id, status: r.status, note: v });
          }}
        />
      ),
    },
    {
      title: '操作',
      dataIndex: 'id',
      render: (id: string) => (
        <Popconfirm title="删除该投递记录？" onConfirm={() => remove.mutate(id)}>
          <Button type="text" danger size="small" icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <Card
      title="投递列表"
      extra={
        <Select
          allowClear
          placeholder="按状态过滤"
          style={{ width: 160 }}
          value={filter}
          onChange={setFilter}
          options={STATUS_OPTIONS.map((v) => ({ value: v, label: APP_STATUS_LABELS[v] }))}
        />
      }
    >
      {(all ?? []).length > 0 && <Dashboard rows={all ?? []} />}
      <Table
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={data ?? []}
        pagination={{ pageSize: 20 }}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无投递记录：浏览器插件每次填写完成后会自动登记到这里"
            />
          ),
        }}
      />
    </Card>
  );
}
