/**
 * 结构化档案编辑器。覆盖核心信息（basic/intention/education/experiences/skills/certificates/
 * self_evaluation）与扩展信息（extended）、附件、问答知识库。
 * 复用 antd Form 的嵌套数据能力，字段命名与 Profile 模型对齐。
 *
 * 未保存保护：编辑即置全局 dirty 标记（App 页切换守卫消费），保存成功清除；
 * 窗口关闭前 beforeunload 提醒；保存栏吸底，长表单无需滚到最底。
 */
import { useEffect, useState } from 'react';
import { Button, Collapse, Divider, Form, Space, message } from 'antd';
import { putProfile } from '../api/client';
import type { Profile } from '../api/types';
import { getUnsaved, setUnsaved } from '../unsaved';
import { datesToDayjs, dayjsToDates } from '../profile-date';
import { BasicFields, EducationFields, ExperienceFields } from './ProfileBasicSections';
import { Attachments, ExtendedFields, QABank } from './ProfileExtendedSections';

export default function ProfileEditor({ profile }: { profile: Profile }) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);

  // 换档案（key 重挂载）重置 dirty
  useEffect(() => {
    setUnsaved(false);
  }, [profile.id]);

  // 窗口关闭前提醒（仅在 dirty 时拦截）
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (getUnsaved()) e.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, []);

  async function onSave() {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const payload = dayjsToDates({ ...profile, ...values }) as Profile;
      await putProfile(profile.id, payload);
      setUnsaved(false);
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
      onValuesChange={() => setUnsaved(true)}
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
      <div
        style={{
          position: 'sticky',
          bottom: 0,
          zIndex: 2,
          background: '#fff',
          padding: '12px 0',
          borderTop: '1px solid #f0f0f0',
        }}
      >
        <Space>
          <Button type="primary" htmlType="submit" loading={saving}>
            保存档案
          </Button>
          <span style={{ color: '#999', fontSize: 12 }}>修改后请保存，切换页面会提醒</span>
        </Space>
      </div>
    </Form>
  );
}
