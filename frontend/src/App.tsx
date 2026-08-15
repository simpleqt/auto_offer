import { useState } from 'react';
import { Layout, Menu, Space, Typography } from 'antd';
import {
  AimOutlined,
  DatabaseOutlined,
  FileSearchOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  SendOutlined,
  RocketOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { health } from './api/client';
import OnboardingPage from './pages/OnboardingPage';
import ProfilesPage from './pages/ProfilesPage';
import ModelsPage from './pages/ModelsPage';
import TasksPage from './pages/TasksPage';
import ReplayPage from './pages/ReplayPage';
import ApplicationsPage from './pages/ApplicationsPage';
import SettingsPage from './pages/SettingsPage';

export type PageKey =
  'onboarding' | 'profiles' | 'models' | 'tasks' | 'replay' | 'applications' | 'settings';

const { Sider, Content } = Layout;

const MENU_ITEMS: { key: PageKey; icon: React.ReactNode; label: string }[] = [
  { key: 'onboarding', icon: <RocketOutlined />, label: '首次引导' },
  { key: 'profiles', icon: <DatabaseOutlined />, label: '档案中心' },
  { key: 'models', icon: <AimOutlined />, label: '模型配置' },
  { key: 'tasks', icon: <PlayCircleOutlined />, label: '任务' },
  { key: 'applications', icon: <SendOutlined />, label: '投递列表' },
  { key: 'replay', icon: <FileSearchOutlined />, label: '回放' },
  { key: 'settings', icon: <SettingOutlined />, label: '设置' },
];

export default function App() {
  const [page, setPage] = useState<PageKey>('onboarding');
  const { data } = useQuery({ queryKey: ['health'], queryFn: health });

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={200} theme="dark">
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 600,
            fontSize: 16,
            letterSpacing: 1,
          }}
        >
          AutoOffer
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[page]}
          items={MENU_ITEMS}
          onClick={(e) => setPage(e.key as PageKey)}
        />
      </Sider>
      <Layout>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          {page === 'onboarding' && <OnboardingPage goTo={setPage} />}
          {page === 'profiles' && <ProfilesPage />}
          {page === 'models' && <ModelsPage />}
          {page === 'tasks' && <TasksPage />}
          {page === 'replay' && <ReplayPage />}
          {page === 'applications' && <ApplicationsPage />}
          {page === 'settings' && <SettingsPage />}
        </Content>
        <Space
          style={{
            padding: '4px 24px',
            justifyContent: 'space-between',
            borderTop: '1px solid #f0f0f0',
          }}
        >
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {data ? `服务 v${data.version} · 数据目录 ${data.data_dir}` : '连接本地服务中…'}
          </Typography.Text>
        </Space>
      </Layout>
    </Layout>
  );
}
