import { useMemo, useState } from 'react';
import {
  Button,
  Card,
  Input,
  message,
  Popconfirm,
  Select,
  Space,
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

export default function ApplicationsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<ApplicationStatus | undefined>();
  const [noteDraft, setNoteDraft] = useState<Record<string, string>>({});
  const { data, isLoading } = useQuery({
    queryKey: ['applications', filter],
    queryFn: () => listApplications(filter),
  });

  const update = useMutation({
    mutationFn: ({ id, status, note }: { id: string; status: ApplicationStatus; note?: string }) =>
      updateApplication(id, { status, note }),
    onSuccess: () => {
      message.success('状态已更新');
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
    { title: '公司', dataIndex: 'company', render: (v: string) => v || <Typography.Text type="secondary">待补</Typography.Text> },
    { title: '岗位', dataIndex: 'position', render: (v: string) => v || <Typography.Text type="secondary">待补</Typography.Text> },
    { title: '状态', dataIndex: 'status', render: (s: ApplicationStatus, r: ApplicationRecord) => (
      <Select
        size="small"
        value={s}
        style={{ width: 110 }}
        options={STATUS_OPTIONS.map((v) => ({ value: v, label: APP_STATUS_LABELS[v] }))}
        onChange={(v) => update.mutate({ id: r.id, status: v })}
      />
    ) },
    { title: '填写统计', render: (_: unknown, r: ApplicationRecord) => (
      <Space size={4}>
        <Tag color="green">{r.fields_filled} 成功</Tag>
        <Tag color="red">{r.fields_failed} 失败</Tag>
        <Tag color="orange">{r.fields_pending} 待确认</Tag>
      </Space>
    ) },
    { title: '填写时间', dataIndex: 'filled_at', render: (v: string) => fmtTime(v) },
    { title: '备注', dataIndex: 'note', render: (_: unknown, r: ApplicationRecord) => (
      <Input
        size="small"
        placeholder="添加备注"
        defaultValue={r.note ?? ''}
        onBlur={(e) => {
          const v = e.target.value.trim();
          if (v !== (r.note ?? '')) update.mutate({ id: r.id, status: r.status, note: v });
        }}
      />
    ) },
    { title: '操作', dataIndex: 'id', render: (id: string) => (
      <Popconfirm title="删除该投递记录？" onConfirm={() => remove.mutate(id)}>
        <Button type="text" danger size="small" icon={<DeleteOutlined />} />
      </Popconfirm>
    ) },
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
      <Table
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={data ?? []}
        pagination={{ pageSize: 20 }}
      />
    </Card>
  );
}
