import { useEffect, useState } from 'react';
import { Button, Card, Result, Space, Steps, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { listModels, listProfiles } from '../api/client';
import type { PageKey } from '../App';

export default function OnboardingPage({ goTo }: { goTo: (p: PageKey) => void }) {
  const { data: models } = useQuery({ queryKey: ['models'], queryFn: listModels });
  const { data: profiles } = useQuery({ queryKey: ['profiles'], queryFn: listProfiles });

  const step1Done = (models?.length ?? 0) > 0;
  const step2Done = (profiles?.length ?? 0) > 0;
  const current = !step1Done ? 0 : !step2Done ? 1 : 2;

  return (
    <Card title="首次引导">
      <Space direction="vertical" size={24} style={{ width: '100%' }}>
        <Steps
          current={current}
          items={[
            { title: '配置模型', description: '添加 OpenAI 兼容端点并探测' },
            { title: '建立档案', description: '上传简历解析或手动填写' },
            { title: '发起任务', description: '粘贴表单 URL 开始自动填写' },
          ]}
        />
        {current === 0 && (
          <Result
            status="info"
            title="先配置一个模型端点"
            subTitle="软件会自动测试连通性与视觉能力；api_key 用系统级加密存储，不会明文回显。"
            extra={<Button type="primary" onClick={() => goTo('models')}>去配置模型</Button>}
          />
        )}
        {current === 1 && (
          <Result
            status="info"
            title="再建立你的个人档案"
            subTitle="上传简历 PDF/Word 自动解析，或手动填写结构化模板；扩展信息按需填写。"
            extra={<Button type="primary" onClick={() => goTo('profiles')}>去建立档案</Button>}
          />
        )}
        {current === 2 && (
          <Result
            status="success"
            title="准备就绪"
            subTitle="模型与档案都已配置完成，可以发起你的第一个自动填写任务了。"
            extra={<Button type="primary" onClick={() => goTo('tasks')}>发起任务</Button>}
          />
        )}
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          提示：填写完成后浏览器窗口会保留，请人工核对报告后再自行提交。
        </Typography.Paragraph>
      </Space>
    </Card>
  );
}
