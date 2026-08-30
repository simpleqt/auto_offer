/**
 * 档案扩展信息表单分组：扩展信息（按需注入）、问答知识库、附件管理。
 * 供 ProfileEditor 以 <Collapse> 折叠面板组织，字段命名与 Profile 模型对齐。
 */
import { useState } from 'react';
import type { FormInstance } from 'antd';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd';
import { CheckOutlined, DeleteOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { activateAttachment, deleteAttachment, uploadAttachment, uploadResume } from '../api/client';
import type { Profile } from '../api/types';

export function ExtendedFields() {
  return (
    <>
      <Typography.Paragraph type="secondary">
        扩展信息遵循「表单不问，档案不给」：仅当目标表单出现对应字段时才注入。可选项，按需填写。
      </Typography.Paragraph>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['extended', 'marital_status']} label="婚姻状况">
            <Select
              options={['未婚', '已婚', '离异'].map((v) => ({ value: v, label: v }))}
              allowClear
            />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'height_cm']} label="身高（cm）">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'weight_kg']} label="体重（kg）">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['extended', 'hukou_location']} label="户口所在地">
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'origin_place']} label="生源地">
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'health_status']} label="健康状况">
            <Input placeholder="如 良好" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['extended', 'party_join_date']} label="入党时间">
            <DatePicker picker="month" style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'travel_willingness']} label="接受出差">
            <Select
              options={['是', '否', '视情况'].map((v) => ({ value: v, label: v }))}
              allowClear
            />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'relocation_willingness']} label="接受调剂">
            <Select
              options={['是', '否', '视情况'].map((v) => ({ value: v, label: v }))}
              allowClear
            />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name={['extended', 'personality', 'hobbies']} label="兴趣爱好">
            <Select mode="tags" open={false} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name={['extended', 'personality', 'specialties']} label="特长">
            <Select mode="tags" open={false} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['extended', 'personality', 'mbti']} label="MBTI">
            <Input placeholder="如 INTJ" />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'personality', 'traits']} label="性格关键词">
            <Select mode="tags" open={false} />
          </Form.Item>
        </Col>
      </Row>
    </>
  );
}

export function QABank() {
  return (
    <Form.List name="qa_bank">
      {(fields, { add, remove }) => (
        <>
          <Table
            size="small"
            pagination={false}
            rowKey="key"
            dataSource={fields}
            columns={[
              {
                title: '问题',
                render: (_, f) => (
                  <Form.Item name={[f.name, 'question']} noStyle>
                    <Input placeholder="如 为什么选择我们公司？" />
                  </Form.Item>
                ),
              },
              {
                title: '回答',
                render: (_, f) => (
                  <Form.Item name={[f.name, 'answer']} noStyle>
                    <Input placeholder="预存答案" />
                  </Form.Item>
                ),
              },
              {
                title: '',
                width: 48,
                render: (_, f) => (
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => remove(f.name)}
                  />
                ),
              },
            ]}
          />
          <Button
            type="dashed"
            icon={<PlusOutlined />}
            block
            onClick={() => add({ question: '', answer: '' })}
          >
            添加问答
          </Button>
        </>
      )}
    </Form.List>
  );
}

export function Attachments({
  profileId,
  form,
  onProfileUpdated,
}: {
  profileId: string;
  form: FormInstance;
  onProfileUpdated: (p: Profile) => void;
}) {
  const [uploading, setUploading] = useState(false);
  const [resumeMode, setResumeMode] = useState<'replace' | 'parse'>('replace');
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const attachments: any[] = Form.useWatch('attachments', form) || [];
  const resumes = attachments
    .map((a, i) => ({ a, i }))
    .filter(({ a }) => a && a.kind === 'resume');
  const activeResumeIdx = (() => {
    const marked = resumes.find(
      ({ a }) => a.meta && String(a.meta.active) === '1',
    );
    return marked ? marked.i : resumes.length ? resumes[0].i : -1;
  })();

  async function doUploadResume(file: File) {
    setUploading(true);
    try {
      const res = await uploadResume(profileId, file, resumeMode);
      onProfileUpdated(res.profile);
      if (resumeMode === 'parse') {
        message.success(
          `简历已上传并解析覆盖档案${res.low_confidence_paths.length ? `（${res.low_confidence_paths.length} 个低置信字段请到各分区复核）` : ''}`,
        );
      } else {
        message.success(`已上传并设为默认简历：${file.name}`);
      }
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function onUploadResume(file: File) {
    if (resumeMode === 'parse') {
      Modal.confirm({
        title: '解析并覆盖档案内容？',
        content:
          '档案的基本信息、教育、实习/工作/项目/科研经历、技能、自评、扩展信息都会以这份简历的解析结果为准（附件列表保留）。当前未保存的手工修改将丢失。',
        okText: '覆盖',
        okButtonProps: { danger: true },
        cancelText: '取消',
        onOk: () => doUploadResume(file),
      });
    } else {
      await doUploadResume(file);
    }
    return false; // 阻止 antd 自动上传
  }

  async function onActivate(index: number) {
    try {
      await activateAttachment(profileId, index);
      // 本地镜像：激活目标，其余简历去掉 active 标记
      const next = attachments.map((a, i) => {
        if (!a || a.kind !== 'resume') return a;
        const meta = { ...(a.meta || {}) };
        if (i === index) meta.active = 1;
        else delete meta.active;
        return { ...a, meta };
      });
      form.setFieldValue('attachments', next);
      message.success('已设为默认简历（填表注入用这份）');
    } catch (e) {
      message.error((e as Error).message);
    }
  }

  async function onDeleteResume(index: number) {
    try {
      const res = await deleteAttachment(profileId, index);
      form.setFieldValue('attachments', res.attachments);
      message.success('已从档案移除该简历（文件保留在本机数据目录）');
    } catch (e) {
      message.error((e as Error).message);
    }
  }

  return (
    <>
      <Card
        size="small"
        title="简历附件（可保留多份，选一份默认）"
        style={{ marginBottom: 16 }}
      >
        <Typography.Paragraph type="secondary">
          填表时「上传简历」控件只注入默认简历。上传新简历可选：仅替换附件（不动档案内容），
          或重新解析并覆盖档案内容。
        </Typography.Paragraph>
        {resumes.length === 0 && (
          <Typography.Paragraph type="warning">
            尚未登记简历附件——请上传一份，否则带「上传简历」的表单没有文件可注入。
          </Typography.Paragraph>
        )}
        {resumes.map(({ a, i }) => (
          <Row key={i} gutter={8} style={{ marginBottom: 6 }} align="middle">
            <Col flex="auto">
              {String(a.path || '').split(/[\\/]/).pop()}（{a.label}）
              {i === activeResumeIdx && (
                <Tag color="blue" style={{ marginLeft: 8 }}>
                  默认
                </Tag>
              )}
            </Col>
            <Col>
              <Space>
                {i !== activeResumeIdx && (
                  <Button size="small" icon={<CheckOutlined />} onClick={() => onActivate(i)}>
                    设为默认
                  </Button>
                )}
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => onDeleteResume(i)}
                />
              </Space>
            </Col>
          </Row>
        ))}
        <Radio.Group
          value={resumeMode}
          onChange={(e) => setResumeMode(e.target.value)}
          style={{ margin: '10px 0' }}
        >
          <Radio value="replace">仅替换附件（不动档案内容）</Radio>
          <Radio value="parse">解析并覆盖档案内容</Radio>
        </Radio.Group>
        <br />
        <Upload showUploadList={false} beforeUpload={onUploadResume} accept=".pdf,.docx,.txt,.md">
          <Button icon={<UploadOutlined />} loading={uploading}>
            上传简历
          </Button>
        </Upload>
      </Card>

      <Form.List name="attachments">
        {(fields, { add, remove }) => (
          <>
            <Typography.Paragraph type="secondary">
              其他附件（证件照/成绩单/证书/作品集等）在填表时按「用途标签 + 类型 + 语言」匹配站点上传控件；
              证件照超限会本地自动压缩。上传后文件保存在本机数据目录，路径随档案一起持久化；
              修改后需点底部「保存档案」。
            </Typography.Paragraph>
          {fields.map(({ key, name }) => (
            <Card
              key={key}
              size="small"
              style={{ marginBottom: 8 }}
              extra={
                <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
              }
            >
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item name={[name, 'kind']} label="类型" rules={[{ required: true }]}>
                    <Select
                      options={[
                        { value: 'resume', label: '简历' },
                        { value: 'photo', label: '证件照' },
                        { value: 'transcript', label: '成绩单' },
                        { value: 'certificate', label: '证书' },
                        { value: 'portfolio', label: '作品集' },
                        { value: 'other', label: '其他' },
                      ]}
                    />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'label']} label="用途标签" rules={[{ required: true }]}>
                    <Input placeholder="如 中文简历 / 一寸白底照" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'language']} label="语言">
                    <Select
                      options={[
                        { value: 'zh', label: '中文' },
                        { value: 'en', label: '英文' },
                      ]}
                      allowClear
                    />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name={[name, 'path']} label="文件路径" rules={[{ required: true }]}>
                <Input placeholder="本机绝对路径" />
              </Form.Item>
            </Card>
          ))}
          <Space>
            <Upload
              showUploadList={false}
              beforeUpload={async (file) => {
                setUploading(true);
                try {
                  const attachment = await uploadAttachment(file, {});
                  add(attachment);
                  message.success(`已上传并保存：${file.name}`);
                } catch (e) {
                  message.error((e as Error).message);
                } finally {
                  setUploading(false);
                }
                return false; // 阻止 antd 自动上传，走自定义逻辑
              }}
            >
              <Button icon={<UploadOutlined />} loading={uploading}>
                上传附件
              </Button>
            </Upload>
            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ meta: {} })}>
              手动添加
            </Button>
          </Space>
        </>
      )}
      </Form.List>
    </>
  );
}
