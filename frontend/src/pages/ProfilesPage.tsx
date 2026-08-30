import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  Empty,
  List,
  message,
  Modal,
  Popconfirm,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
} from 'antd';
import { DeleteOutlined, FileTextOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { deleteProfile, getProfile, listProfiles, parseResume, putProfile } from '../api/client';
import { emptyProfile, fmtTime, newProfileId } from '../profile-utils';
import { getUnsaved, setUnsaved } from '../unsaved';
import ProfileEditor from './ProfileEditor';

export default function ProfilesPage() {
  const qc = useQueryClient();
  const { data: profiles, isLoading } = useQuery({
    queryKey: ['profiles'],
    queryFn: listProfiles,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const { data: activeProfile, isLoading: profileLoading } = useQuery({
    queryKey: ['profile', selectedId],
    queryFn: () => getProfile(selectedId!),
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

  /** 有未保存修改时先确认再执行会丢弃编辑内容的操作。 */
  function confirmIfUnsaved(action: () => void, title = '有未保存的档案修改') {
    if (!getUnsaved()) {
      action();
      return;
    }
    Modal.confirm({
      title,
      content: '当前档案有未保存的修改，继续将丢失这些修改。',
      okText: '丢弃修改并继续',
      okButtonProps: { danger: true },
      cancelText: '留下修改',
      onOk: () => {
        setUnsaved(false);
        action();
      },
    });
  }

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
    if (getUnsaved()) {
      message.warning('当前档案有未保存的修改，请先保存或放弃后再解析新简历');
      return false;
    }
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
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={8} xl={8}>
        <Card
          title="档案列表"
          extra={
            <Space>
              <Upload
                accept=".pdf,.docx,.doc,.txt,.md"
                showUploadList={false}
                beforeUpload={handleParse}
              >
                <Button icon={<UploadOutlined />} loading={uploading}>
                  解析简历
                </Button>
              </Upload>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                loading={create.isPending}
                onClick={() => confirmIfUnsaved(() => create.mutate())}
              >
                新建
              </Button>
            </Space>
          }
        >
          {isLoading ? (
            <Spin />
          ) : (profiles ?? []).length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="还没有档案：上传简历自动解析，或新建空白档案"
            >
              <Upload
                accept=".pdf,.docx,.doc,.txt,.md"
                showUploadList={false}
                beforeUpload={handleParse}
              >
                <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
                  解析第一份简历
                </Button>
              </Upload>
            </Empty>
          ) : (
            <List
              dataSource={profiles ?? []}
              renderItem={(p) => (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    background: p.id === selectedId ? '#eef3ff' : undefined,
                    borderInlineStart:
                      p.id === selectedId ? '3px solid #2e5be6' : '3px solid transparent',
                    paddingInlineStart: 10,
                    borderRadius: 6,
                  }}
                  onClick={() =>
                    p.id !== selectedId &&
                    confirmIfUnsaved(() => setSelectedId(p.id), '切换档案将丢失未保存的修改')
                  }
                  actions={[
                    <Popconfirm
                      key="del"
                      title="删除该档案？"
                      onConfirm={() => remove.mutate(p.id)}
                    >
                      <Button type="text" danger size="small" icon={<DeleteOutlined />} />
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <Typography.Text strong>{p.label || p.name || p.id}</Typography.Text>
                        {p.attachments > 0 && (
                          <Tag icon={<FileTextOutlined />}>{p.attachments} 附件</Tag>
                        )}
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
      <Col xs={24} lg={16} xl={16}>
        <Card title="档案编辑" extra={activeProfile && <Tag>{activeProfile.label}</Tag>}>
          {profileLoading ? (
            <Spin />
          ) : activeProfile ? (
            <ProfileEditor key={activeProfile.id} profile={activeProfile} />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="从左侧选择一个档案，或上传简历 PDF/Word 自动解析、或新建空白档案。"
            />
          )}
        </Card>
      </Col>
    </Row>
  );
}
