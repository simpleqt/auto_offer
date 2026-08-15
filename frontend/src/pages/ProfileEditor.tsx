/**
 * 结构化档案编辑器。覆盖核心信息（basic/intention/education/experiences/skills/certificates/
 * self_evaluation）与扩展信息（extended）、附件、问答知识库。
 * 复用 antd Form 的嵌套数据能力，字段命名与 Profile 模型对齐。
 */
import { useState } from 'react';
import {
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Divider,
  Form,
  Input,
  InputNumber,
  message,
  Row,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import dayjs, { type Dayjs } from 'dayjs';
import { putProfile } from '../api/client';
import type { DateYM, Profile } from '../api/types';
import { DEGREE_OPTIONS, EXPERIENCE_KIND_LABELS, GENDER_OPTIONS } from '../constants';

const { TextArea } = Input;

/** 判断一个对象是否是 DateYM 形状（{year, month?, day?}）。 */
function isDateYM(v: unknown): v is DateYM {
  if (v == null || typeof v !== 'object') return false;
  const o = v as Record<string, unknown>;
  return (
    typeof o.year === 'number' &&
    ('month' in o || 'day' in o)
  );
}

/** 递归把 Profile 中的 DateYM 结构转换为 antd DatePicker 需要的 Dayjs。 */
function datesToDayjs<T>(value: T): T {
  if (Array.isArray(value)) return value.map(datesToDayjs) as unknown as T;
  if (isDateYM(value)) {
    return dayjs(
      `${value.year}-${String(value.month ?? 1).padStart(2, '0')}-${String(value.day ?? 1).padStart(2, '0')}`,
    ) as unknown as T;
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = datesToDayjs(v);
    }
    return out as unknown as T;
  }
  return value;
}

/** 递归把 Form 值中的 Dayjs 转回后端 DateYM 结构。 */
function dayjsToDates<T>(value: T): T {
  if (Array.isArray(value)) return value.map(dayjsToDates) as unknown as T;
  if (dayjs.isDayjs(value)) {
    return { year: value.year(), month: value.month() + 1, day: value.date() } as unknown as T;
  }
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = dayjsToDates(v);
    }
    return out as unknown as T;
  }
  return value;
}

export default function ProfileEditor({ profile }: { profile: Profile }) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  async function onSave() {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const payload = dayjsToDates({ ...profile, ...values }) as Profile;
      await putProfile(profile.id, payload);
      message.success('档案已保存');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={datesToDayjs(profile)}
      onFinish={onSave}
    >
      <Collapse
        defaultActiveKey={['basic', 'education', 'experience', 'extended', 'qa', 'attachments']}
        items={[
          { key: 'basic', label: '基本信息', children: <BasicFields /> },
          { key: 'education', label: '教育经历', children: <EducationFields /> },
          { key: 'experience', label: '实习 / 工作 / 项目经历', children: <ExperienceFields /> },
          { key: 'extended', label: '扩展信息（按需注入）', children: <ExtendedFields /> },
          { key: 'qa', label: '问答知识库', children: <QABank /> },
          { key: 'attachments', label: '附件管理', children: <Attachments /> },
        ]}
      />
      <Divider />
      <Space>
        <Button type="primary" htmlType="submit" loading={saving}>保存档案</Button>
      </Space>
    </Form>
  );
}

function BasicFields() {
  return (
    <>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['basic', 'name']} label="姓名" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['basic', 'gender']} label="性别">
            <Select options={GENDER_OPTIONS.map((g) => ({ value: g, label: g }))} allowClear />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['basic', 'birth_date']} label="出生日期">
            <DatePicker picker="month" style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['basic', 'phone']} label="电话" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['basic', 'email']} label="邮箱" rules={[{ required: true, type: 'email' }]}>
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['basic', 'political_status']} label="政治面貌">
            <Input placeholder="如 中共党员 / 共青团员 / 群众" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['basic', 'native_place']} label="籍贯">
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['basic', 'current_city']} label="现居城市">
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item
            name={['basic', 'id_number']}
            label="身份证号"
            tooltip="restricted 级：表单命中时需单独授权本次使用"
          >
            <Input.Password placeholder="加密存储，界面脱敏显示" />
          </Form.Item>
        </Col>
      </Row>
      <Divider orientation="left" plain>求职意向</Divider>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['intention', 'position']} label="期望职位">
            <Input />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['intention', 'city']} label="期望城市">
            <Select mode="tags" placeholder="回车添加城市" open={false} />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['intention', 'salary_expectation']} label="期望薪资">
            <Input placeholder="如 15-20k" />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col span={12}>
          <Form.Item name={['skills']} label="技能（回车添加）">
            <Select mode="tags" open={false} />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name={['certificates']} label="证书（回车添加）">
            <Select mode="tags" open={false} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name={['self_evaluation']} label="自我评价">
        <TextArea rows={3} />
      </Form.Item>
    </>
  );
}

function EducationFields() {
  return (
    <Form.List name="education">
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name }) => (
            <Card
              key={key}
              size="small"
              style={{ marginBottom: 12 }}
              extra={<Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />}
            >
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item name={[name, 'school']} label="学校" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'major']} label="专业">
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'degree']} label="学历">
                    <Select options={DEGREE_OPTIONS.map((d) => ({ value: d, label: d }))} allowClear />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item name={[name, 'period', 'start']} label="开始时间">
                    <DatePicker picker="month" style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'period', 'end']} label="结束时间（空=至今）">
                    <DatePicker picker="month" style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'gpa']} label="GPA">
                    <Input />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name={[name, 'description']} label="描述">
                <TextArea rows={2} />
              </Form.Item>
            </Card>
          ))}
          <Button type="dashed" icon={<PlusOutlined />} block onClick={() => add({ period: {} })}>
            添加教育经历
          </Button>
        </>
      )}
    </Form.List>
  );
}

function ExperienceFields() {
  return (
    <Form.List name="experiences">
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name }) => (
            <Card
              key={key}
              size="small"
              style={{ marginBottom: 12 }}
              extra={<Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />}
            >
              <Row gutter={12}>
                <Col span={6}>
                  <Form.Item name={[name, 'kind']} label="类型" rules={[{ required: true }]}>
                    <Select options={Object.entries(EXPERIENCE_KIND_LABELS).map(([v, l]) => ({ value: v, label: l }))} />
                  </Form.Item>
                </Col>
                <Col span={9}>
                  <Form.Item name={[name, 'organization']} label="组织 / 公司" rules={[{ required: true }]}>
                    <Input />
                  </Form.Item>
                </Col>
                <Col span={9}>
                  <Form.Item name={[name, 'title']} label="职位 / 角色">
                    <Input />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item name={[name, 'period', 'start']} label="开始时间">
                    <DatePicker picker="month" style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'period', 'end']} label="结束时间（空=至今）">
                    <DatePicker picker="month" style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name={[name, 'description']} label="描述">
                <TextArea rows={2} />
              </Form.Item>
            </Card>
          ))}
          <Button type="dashed" icon={<PlusOutlined />} block onClick={() => add({ period: {}, highlights: [] })}>
            添加经历
          </Button>
        </>
      )}
    </Form.List>
  );
}

function ExtendedFields() {
  return (
    <>
      <Typography.Paragraph type="secondary">
        扩展信息遵循「表单不问，档案不给」：仅当目标表单出现对应字段时才注入。可选项，按需填写。
      </Typography.Paragraph>
      <Row gutter={12}>
        <Col span={8}>
          <Form.Item name={['extended', 'marital_status']} label="婚姻状况">
            <Select options={['未婚', '已婚', '离异'].map((v) => ({ value: v, label: v }))} allowClear />
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
            <Select options={['是', '否', '视情况'].map((v) => ({ value: v, label: v }))} allowClear />
          </Form.Item>
        </Col>
        <Col span={8}>
          <Form.Item name={['extended', 'relocation_willingness']} label="接受调剂">
            <Select options={['是', '否', '视情况'].map((v) => ({ value: v, label: v }))} allowClear />
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

function QABank() {
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
                  <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(f.name)} />
                ),
              },
            ]}
          />
          <Button type="dashed" icon={<PlusOutlined />} block onClick={() => add({ question: '', answer: '' })}>
            添加问答
          </Button>
        </>
      )}
    </Form.List>
  );
}

function Attachments() {
  return (
    <Form.List name="attachments">
      {(fields, { add, remove }) => (
        <>
          <Typography.Paragraph type="secondary">
            附件在填表时按「用途标签 + 类型 + 语言」匹配站点上传控件；证件照超限会本地自动压缩。
          </Typography.Paragraph>
          {fields.map(({ key, name }) => (
            <Card key={key} size="small" style={{ marginBottom: 8 }}
              extra={<Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />}>
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item name={[name, 'kind']} label="类型" rules={[{ required: true }]}>
                    <Select options={[
                      { value: 'resume', label: '简历' },
                      { value: 'photo', label: '证件照' },
                      { value: 'transcript', label: '成绩单' },
                      { value: 'certificate', label: '证书' },
                      { value: 'portfolio', label: '作品集' },
                      { value: 'other', label: '其他' },
                    ]} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'label']} label="用途标签" rules={[{ required: true }]}>
                    <Input placeholder="如 中文简历 / 一寸白底照" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name={[name, 'language']} label="语言">
                    <Select options={[{ value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} allowClear />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name={[name, 'path']} label="文件路径" rules={[{ required: true }]}>
                <Input placeholder="本机绝对路径" />
              </Form.Item>
            </Card>
          ))}
          <Button type="dashed" icon={<PlusOutlined />} block onClick={() => add({ meta: {} })}>
            添加附件
          </Button>
        </>
      )}
    </Form.List>
  );
}
