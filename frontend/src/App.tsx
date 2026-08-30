import { useState } from 'react';
import { Badge, Layout, Menu, Modal, Space, Tag, Typography } from 'antd';
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
import { getUnsaved, setUnsaved } from './unsaved';
import OnboardingPage from './pages/OnboardingPage';
import ProfilesPage from './pages/ProfilesPage';
import ModelsPage from './pages/ModelsPage';
import TasksPage from './pages/TasksPage';
import ReplayPage from './pages/ReplayPage';
import ApplicationsPage from './pages/ApplicationsPage';
import SettingsPage from './pages/SettingsPage';

export type PageKey =
  'onboarding' | 'profiles' | 'models' | 'tasks' | 'replay' | 'applications' | 'settings';

const { Sider, Content, Header } = Layout;

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
  const [collapsed, setCollapsed] = useState(false);
  const { data } = useQuery({
    queryKey: ['health'],
    queryFn: health,
    // 顶栏服务状态徽标的数据源：周期刷新，本地服务起停能及时反映
    refetchInterval: 30_000,
    retry: 0,
  });

  function switchPage(next: PageKey) {
    if (next === page) return;
    if (getUnsaved()) {
      Modal.confirm({
        title: '有未保存的档案修改',
        content: '离开当前页面将丢失未保存的修改，确定离开吗？',
        okText: '离开',
        okButtonProps: { danger: true },
        cancelText: '留下修改',
        onOk: () => {
          setUnsaved(false);
          setPage(next);
        },
      });
      return;
    }
    setPage(next);
  }

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider
        width={200}
        theme="dark"
        breakpoint="lg"
        collapsedWidth={48}
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
      >
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            color: '#fff',
            fontWeight: 600,
            fontSize: 16,
            letterSpacing: 1,
            overflow: 'hidden',
            whiteSpace: 'nowrap',
          }}
        >
          <img
            src="/logo.png"
            alt="AutoOffer"
            style={{ width: 26, height: 26, borderRadius: 6, flex: 'none' }}
          />
          {!collapsed && <span>AutoOffer</span>}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[page]}
          items={MENU_ITEMS}
          onClick={(e) => switchPage(e.key as PageKey)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: 52,
            lineHeight: '52px',
            borderBottom: '1px solid #eef0f4',
          }}
        >
          <Typography.Title level={5} style={{ margin: 0 }}>
            {MENU_ITEMS.find((m) => m.key === page)?.label}
          </Typography.Title>
          <Space size={12}>
            {data?.status === 'ok' ? (
              <Badge status="success" text={`本地服务在线 · 127.0.0.1:${data.port}`} />
            ) : (
              <Badge status="error" text="本地服务未运行" />
            )}
            {data && <Tag style={{ marginInlineEnd: 0 }}>v{data.version}</Tag>}
          </Space>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          {page === 'onboarding' && <OnboardingPage goTo={switchPage} />}
          {page === 'profiles' && <ProfilesPage />}
          {page === 'models' && <ModelsPage />}
          {page === 'tasks' && <TasksPage />}
          {page === 'replay' && <ReplayPage />}
          {page === 'applications' && <ApplicationsPage />}
          {page === 'settings' && <SettingsPage />}
        </Content>
      </Layout>
    </Layout>
  );
}
