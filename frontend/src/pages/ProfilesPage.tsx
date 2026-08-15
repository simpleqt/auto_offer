import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  List,
  message,
  Popconfirm,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
} from 'antd';
import {
  DeleteOutlined,
  FileTextOutlined,
  PlusOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { deleteProfile, getProfile, listProfiles, parseResume, putProfile } from '../api/client';
import type { Profile } from '../api/types';
import { emptyProfile, fmtTime, newProfileId } from '../profile-utils';
import ProfileEditor from './ProfileEditor';
import type { PageKey } from '../App';

export default function ProfilesPage({ goTo }: { goTo: (p: PageKey) => void }) {
  const qc = useQueryClient();
  const { data: profiles, isLoading } = useQuery({
    queryKey: ['profiles'],
    queryFn: listProfiles,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [creating, setCreating] = useState(false);

  const { data: activeProfile, isLoading: profileLoading } = useQuery({
    queryKey: ['profile', selectedId],
    queryFn: () => getProfile(selectedId!).then((r) => r.payload),
    enabled: !!selectedId,
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteProfile(id),
    onSuccess: () => {
      message.success('已删除');
      qc.invalidateQueries({ queryKey: ['profiles'] });
      if (selectedId) setSelectedId(null);
    },
    onError: (e: Error) => message.error(e.message),
  });

  const create = useMutation({
    mutationFn: async () => {
      const id = newProfileId();
      const profile = emptyProfile(id);
      profile.label = '未命名档案';
      await putProfile(id, profile);
      return id;
    },
    onSuccess: (id) => {
      message.success('已创建空白档案，请填写核心信息');
      qc.invalidateQueries({ queryKey: ['profiles'] });
      setSelectedId(id);
    },
    onError: (e: Error) => message.error(e.message),
  });

  async function handleParse(file: File) {
    setUploading(true);
    try {
      const r = await parseResume(file);
      message.success(`解析完成，低置信字段 ${r.low_confidence_paths.length} 个请核对`);
      qc.invalidateQueries({ queryKey: ['profiles'] });
      setSelectedId(r.profile.id);
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setUploading(false);
    }
    return false; // 阻止 antd 自动上传
  }

  return (
    <Row gutter={16}>
      <Col span={8}>
        <Card
          title="档案列表"
          extra={
            <Space>
              <Upload
                accept=".pdf,.docx,.doc,.txt"
                showUploadList={false}
                beforeUpload={handleParse}
              >
                <Button icon={<UploadOutlined />} loading={uploading}>解析简历</Button>
              </Upload>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                loading={creating || create.isPending}
                onClick={() => create.mutate()}
              >
                新建
              </Button>
            </Space>
          }
        >
          {isLoading ? (
            <Spin />
          ) : (
            <List
              dataSource={profiles ?? []}
              renderItem={(p) => (
                <List.Item
                  style={{ cursor: 'pointer', background: p.id === selectedId ? '#f0f5ff' : undefined }}
                  onClick={() => setSelectedId(p.id)}
                  actions={[
                    <Popconfirm key="del" title="删除该档案？" onConfirm={() => remove.mutate(p.id)}>
                      <Button type="text" danger size="small" icon={<DeleteOutlined />} />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <Typography.Text strong>{p.label || p.name || p.id}</Typography.Text>
                        {p.attachments > 0 && <Tag icon={<FileTextOutlined />}>{p.attachments} 附件</Tag>}
                      </Space>
                    }
                    description={`更新于 ${fmtTime(p.updated_at)}`}
                  />
                </List.Item>
              )}
            />
          )}
        </Card>
      </Col>
      <Col span={16}>
        <Card title="档案编辑" extra={activeProfile && <Tag>{activeProfile.label}</Tag>}>
          {profileLoading ? (
            <Spin />
          ) : activeProfile ? (
            <ProfileEditor key={activeProfile.id} profile={activeProfile} />
          ) : (
            <Typography.Paragraph type="secondary">
              从左侧选择一个档案，或上传简历 PDF/Word 自动解析、或新建空白档案。
            </Typography.Paragraph>
          )}
        </Card>
      </Col>
    </Row>
  );
}
