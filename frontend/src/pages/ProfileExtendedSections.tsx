/**
 * 档案扩展信息表单分组：扩展信息（按需注入）、问答知识库、附件管理。
 * 供 ProfileEditor 以 <Collapse> 折叠面板组织，字段命名与 Profile 模型对齐。
 */
import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Typography,
  Upload,
  message,
} from 'antd';
import { DeleteOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import { uploadAttachment } from '../api/client';

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

export function Attachments() {
  const [uploading, setUploading] = useState(false);

  return (
    <Form.List name="attachments">
      {(fields, { add, remove }) => (
        <>
          <Typography.Paragraph type="secondary">
            附件在填表时按「用途标签 + 类型 + 语言」匹配站点上传控件；证件照超限会本地自动压缩。
            上传后文件保存在本机数据目录，路径随档案一起持久化。
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
  );
}
