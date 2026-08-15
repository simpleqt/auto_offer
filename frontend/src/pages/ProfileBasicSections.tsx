/**
 * 档案核心信息表单分组：基本信息（含求职意向）、教育经历、实习/工作/项目经历。
 * 供 ProfileEditor 以 <Collapse> 折叠面板组织，字段命名与 Profile 模型对齐。
 */
import { Button, Card, Col, DatePicker, Divider, Form, Input, Row, Select } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { DEGREE_OPTIONS, EXPERIENCE_KIND_LABELS, GENDER_OPTIONS } from '../constants';

const { TextArea } = Input;

export function BasicFields() {
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
          <Form.Item
            name={['basic', 'email']}
            label="邮箱"
            rules={[{ required: true, type: 'email' }]}
          >
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
      <Divider orientation="left" plain>
        求职意向
      </Divider>
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

export function EducationFields() {
  return (
    <Form.List name="education">
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name }) => (
            <Card
              key={key}
              size="small"
              style={{ marginBottom: 12 }}
              extra={
                <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
              }
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
                    <Select
                      options={DEGREE_OPTIONS.map((d) => ({ value: d, label: d }))}
                      allowClear
                    />
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

export function ExperienceFields() {
  return (
    <Form.List name="experiences">
      {(fields, { add, remove }) => (
        <>
          {fields.map(({ key, name }) => (
            <Card
              key={key}
              size="small"
              style={{ marginBottom: 12 }}
              extra={
                <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(name)} />
              }
            >
              <Row gutter={12}>
                <Col span={6}>
                  <Form.Item name={[name, 'kind']} label="类型" rules={[{ required: true }]}>
                    <Select
                      options={Object.entries(EXPERIENCE_KIND_LABELS).map(([v, l]) => ({
                        value: v,
                        label: l,
                      }))}
                    />
                  </Form.Item>
                </Col>
                <Col span={9}>
                  <Form.Item
                    name={[name, 'organization']}
                    label="组织 / 公司"
                    rules={[{ required: true }]}
                  >
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
          <Button
            type="dashed"
            icon={<PlusOutlined />}
            block
            onClick={() => add({ period: {}, highlights: [] })}
          >
            添加经历
          </Button>
        </>
      )}
    </Form.List>
  );
}
