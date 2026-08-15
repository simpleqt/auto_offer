import { Card, Descriptions, Space, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { health } from '../api/client';

export default function SettingsPage() {
  const { data } = useQuery({ queryKey: ['health'], queryFn: health });

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="本地服务">
        <Descriptions column={2} size="small">
          <Descriptions.Item label="版本">{data?.version ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="状态">{data?.status ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="数据目录" span={2}>
            <Typography.Text copyable code>
              {data?.data_dir ?? '—'}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="任务浏览器">
            {data?.headless ? '无头模式' : '可见窗口'}
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="关于">
        <Typography.Paragraph>
          AutoOffer —— 通用简历自动填写智能体。数据全部保存在本机，仅向您配置的模型端点发送数据。
          填写结果需人工审核后自行提交，请遵守目标网站服务条款。
        </Typography.Paragraph>
        <Typography.Paragraph type="secondary">
          并发上限、浏览器可见性、语言等运行参数当前由服务端配置控制（见
          server/autooffer_server/config.py 与启动参数）。
        </Typography.Paragraph>
      </Card>
    </Space>
  );
}
