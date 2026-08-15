/**
 * 结构化档案编辑器。覆盖核心信息（basic/intention/education/experiences/skills/certificates/
 * self_evaluation）与扩展信息（extended）、附件、问答知识库。
 * 复用 antd Form 的嵌套数据能力，字段命名与 Profile 模型对齐。
 */
import { useState } from 'react';
import { Button, Collapse, Divider, Form, Space, message } from 'antd';
import { putProfile } from '../api/client';
import type { Profile } from '../api/types';
import { datesToDayjs, dayjsToDates } from '../profile-date';
import { BasicFields, EducationFields, ExperienceFields } from './ProfileBasicSections';
import { Attachments, ExtendedFields, QABank } from './ProfileExtendedSections';

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
    <Form form={form} layout="vertical" initialValues={datesToDayjs(profile)} onFinish={onSave}>
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
        <Button type="primary" htmlType="submit" loading={saving}>
          保存档案
        </Button>
      </Space>
    </Form>
  );
}
