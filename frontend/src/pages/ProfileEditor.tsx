/**
 * 结构化档案编辑器。覆盖核心信息（basic/intention/education/experiences/skills/certificates/
 * self_evaluation）与扩展信息（extended）、附件、问答知识库。
 * 复用 antd Form 的嵌套数据能力，字段命名与 Profile 模型对齐。
 *
 * 未保存保护：编辑即置全局 dirty 标记（App 页切换守卫消费），保存成功清除；
 * 窗口关闭前 beforeunload 提醒；保存栏吸底，长表单无需滚到最底。
 */
import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  Collapse,
  Divider,
  Form,
  Progress,
  Space,
  Tag,
  Typography,
  message,
} from 'antd';
import { putProfile } from '../api/client';
import type { Profile } from '../api/types';
import { getUnsaved, setUnsaved } from '../unsaved';
import { datesToDayjs, dayjsToDates } from '../profile-date';
import { profileCompleteness } from '../completeness';
import { BasicFields, EducationFields, ExperienceFields } from './ProfileBasicSections';
import { Attachments, ExtendedFields, QABank } from './ProfileExtendedSections';

export default function ProfileEditor({ profile }: { profile: Profile }) {
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [completeness, setCompleteness] = useState(() => profileCompleteness(profile));

  // 换档案（key 重挂载）重置 dirty / 完整度
  useEffect(() => {
    setUnsaved(false);
    setDirty(false);
    setCompleteness(profileCompleteness(profile));
  }, [profile.id]);

  // 窗口关闭前提醒（仅在 dirty 时拦截）
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (getUnsaved()) e.preventDefault();
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, []);

  // Ctrl+S 保存档案（表单页肌肉记忆）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
        e.preventDefault();
        if (!saving) form.submit();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [form, saving]);

  async function onSave() {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const payload = dayjsToDates({ ...profile, ...values }) as Profile;
      await putProfile(profile.id, payload);
      setUnsaved(false);
      setDirty(false);
      message.success('档案已保存');
    } catch (e) {
      message.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  /** 服务端已改档案（如简历解析覆盖）→ 整表刷新为服务端版本 */
  function onProfileUpdated(fresh: Profile) {
    form.setFieldsValue(datesToDayjs(fresh));
    setUnsaved(false);
    setDirty(false);
  }

  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={datesToDayjs(profile)}
      onValuesChange={(_, values) => {
        setUnsaved(true);
        setDirty(true);
        // 边填边算：values 是增量，与当前档案浅合并后评分
        setCompleteness(profileCompleteness({ ...profile, ...values }));
      }}
      onFinish={onSave}
    >
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <Progress
            type="circle"
            size={56}
            percent={completeness.score}
            strokeColor={completeness.score >= 80 ? '#52c41a' : '#2e5be6'}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <Typography.Text strong>档案完整度 {completeness.score}%</Typography.Text>
            <div style={{ marginTop: 4 }}>
              {completeness.missing.length === 0 ? (
                <Typography.Text type="success" style={{ fontSize: 12 }}>
                  已非常完整——绝大多数站点字段都能直填
                </Typography.Text>
              ) : (
                <Space size={4} wrap>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    还可补充：
                  </Typography.Text>
                  {completeness.missing.map((m) => (
                    <Tag key={m} style={{ marginInlineEnd: 0 }}>
                      {m}
                    </Tag>
                  ))}
                </Space>
              )}
            </div>
          </div>
        </div>
      </Card>
      <Collapse
        defaultActiveKey={['basic', 'education', 'experience', 'extended', 'qa', 'attachments']}
        items={[
          { key: 'basic', label: '基本信息', children: <BasicFields /> },
          { key: 'education', label: '教育经历', children: <EducationFields /> },
          { key: 'experience', label: '实习 / 工作 / 项目经历', children: <ExperienceFields /> },
          { key: 'extended', label: '扩展信息（按需注入）', children: <ExtendedFields /> },
          { key: 'qa', label: '问答知识库', children: <QABank /> },
          {
            key: 'attachments',
            label: '附件管理',
            children: (
              <Attachments profileId={profile.id} form={form} onProfileUpdated={onProfileUpdated} />
            ),
          },
        ]}
      />
      <Divider />
      <div
        style={{
          position: 'sticky',
          bottom: 0,
          zIndex: 2,
          background: dirty ? 'var(--ao-warn-bg)' : 'var(--ao-panel)',
          padding: '12px 0',
          borderTop: dirty ? '1px solid var(--ao-warn-line)' : '1px solid var(--ao-line)',
          transition: 'background 0.2s',
        }}
      >
        <Space>
          <Button type="primary" htmlType="submit" loading={saving}>
            保存档案
          </Button>
          <span style={{ color: dirty ? 'var(--ao-warn-text)' : 'var(--ao-text-3)', fontSize: 12 }}>
            {dirty ? '● 有未保存的修改（Ctrl+S 保存）' : 'Ctrl+S 可快速保存；切换页面会提醒未保存'}
          </span>
        </Space>
      </div>
    </Form>
  );
}
