import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  List,
  message,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { PlayCircleOutlined, ReloadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { cancelTask, createTask, listProfiles, listTasks, resumeTask } from '../api/client';
import { TASK_STATE_COLORS, TASK_STATE_LABELS } from '../constants';
import TaskDetail from './TaskDetail';

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
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={8}>
        <Card title="新建任务" style={{ marginBottom: 16 }}>
          <Form form={form} layout="vertical" onFinish={(v) => create.mutate(v)}>
            <Form.Item
              name="url"
              label="目标表单 URL"
              rules={[{ required: true, type: 'url', message: '请输入合法 URL' }]}
            >
              <Input placeholder="https://example.com/apply" allowClear />
            </Form.Item>
            <Form.Item
              name="profile_id"
              label="使用档案"
              rules={[{ required: true, message: '请选择档案' }]}
            >
              <Select
                placeholder="选择档案"
                options={(profiles ?? []).map((p) => ({
                  value: p.id,
                  label: p.label || p.name || p.id,
                }))}
              />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              icon={<PlayCircleOutlined />}
              loading={create.isPending}
              block
            >
              开始填写
            </Button>
          </Form>
        </Card>

        <Card
          title="任务列表"
          extra={
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => qc.invalidateQueries({ queryKey: ['tasks'] })}
            />
          }
        >
          {isLoading ? (
            <Spin />
          ) : (tasks?.length ?? 0) === 0 ? (
            <Empty description="暂无任务" />
          ) : (
            <List
              dataSource={tasks}
              renderItem={(t) => (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    background: t.id === selectedId ? '#f0f5ff' : undefined,
                  }}
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

      <Col xs={24} lg={16}>
        {selectedId ? (
          <TaskDetail
            key={selectedId}
            taskId={selectedId}
            onResume={() => resume.mutate(selectedId)}
            onCancel={() => cancel.mutate(selectedId)}
            onChanged={() => qc.invalidateQueries({ queryKey: ['tasks'] })}
          />
        ) : (
          <Card>
            <Empty description="从左侧选择任务查看实时进度" />
          </Card>
        )}
      </Col>
    </Row>
  );
}
