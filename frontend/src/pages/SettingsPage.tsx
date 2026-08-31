import { useEffect } from 'react';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  InputNumber,
  message,
  Radio,
  Space,
  Switch,
  Typography,
} from 'antd';
import { SaveOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getSettings, health, putSettings } from '../api/client';
import type { AppSettings } from '../api/types';
import { useThemeMode } from '../theme';
import type { ThemeMode } from '../theme';

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: 'auto', label: '跟随系统' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
];

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['health'], queryFn: health });
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: getSettings });
  const [form] = Form.useForm<AppSettings>();
  const { mode: themeMode, setMode: setThemeMode } = useThemeMode();

  useEffect(() => {
    if (settings) form.setFieldsValue(settings);
  }, [settings, form]);

  const save = useMutation({
    mutationFn: (body: AppSettings) => putSettings(body),
    onSuccess: (_d, body) => {
      const portChanged = body.service_port !== data?.port;
      message.success(
        portChanged ? '设置已保存，服务端口重启软件后生效' : '设置已保存，下一个任务生效',
      );
      qc.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: (e: Error) => message.error(e.message),
  });

  const browserMode = Form.useWatch('browser_mode', form);

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="推荐使用浏览器插件填写"
        description="在 Chrome 加载本软件目录下的 extension/ 文件夹即可一键直填招聘表单（规则直填优先，冷门问法 AI 仅做字段映射，档案值不出本机）。安装步骤见 README「浏览器插件快速上手」。下方浏览器连接方式属于传统模式，保留可用。"
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          browser_mode: 'managed',
          cdp_endpoint: '',
          minimize_on_startup: false,
          service_port: 8765,
        }}
        onFinish={(vals) => save.mutate(vals)}
      >
        <Card title="浏览器连接方式" style={{ marginBottom: 16 }}>
          <Form.Item
            name="browser_mode"
            label="任务在哪个浏览器里填写"
            extra="选择软件自控浏览器（免配置、登录态跨任务保留），或连接你日常用的 Chrome/Edge 当前页面"
          >
            <Radio.Group
              options={[
                { value: 'managed', label: '软件自控浏览器（推荐）' },
                { value: 'cdp', label: '我日常用的 Chrome / Edge' },
              ]}
            />
          </Form.Item>

          {browserMode === 'cdp' && (
            <>
              <Form.Item
                name="cdp_endpoint"
                label="浏览器远程调试地址（CDP）"
                rules={[{ required: true, message: '请填写 CDP 地址' }]}
                extra="需用调试端口启动浏览器，例如 chrome.exe --remote-debugging-port=9222"
              >
                <Input placeholder="http://127.0.0.1:9222" />
              </Form.Item>
              <Alert
                type="info"
                showIcon
                message="如何开启调试端口"
                description={
                  <Typography.Text>
                    关闭浏览器后用命令行启动：
                    <Typography.Text code>
                      {'chrome.exe --remote-debugging-port=9222'}
                    </Typography.Text>
                    或
                    <Typography.Text code>
                      {'msedge.exe --remote-debugging-port=9222'}
                    </Typography.Text>
                    ，再在这里填上地址。
                  </Typography.Text>
                }
              />
            </>
          )}

          {browserMode === 'managed' && (
            <Alert
              type="success"
              showIcon
              message="软件会自动管理浏览器"
              description="任务启动时软件在后台拉起自己的浏览器（登录态保存在本机），无需任何手动配置。"
            />
          )}

          <Form.Item
            name="minimize_on_startup"
            label="主窗口启动后自动最小化"
            valuePropName="checked"
            extra="静默待命；任务需要时软件直接操作目标页面"
          >
            <Switch />
          </Form.Item>

          <Form.Item
            name="auto_submit"
            label="填写完成后自动提交"
            valuePropName="checked"
            extra="开启后：走完全部步骤即自动点击页面上的「提交/投递」按钮（默认关闭，由你人工审核后提交）"
            style={{ marginBottom: 0 }}
          >
            <Switch />
          </Form.Item>
        </Card>

        <Card title="服务端口" style={{ marginBottom: 16 }}>
          <Form.Item
            name="service_port"
            label="本地服务监听端口"
            rules={[{ required: true, message: '请填写端口' }]}
            extra={
              <span>
                默认 8765；被其他程序占用时可换端口避免冲突。保存后
                <Typography.Text strong>重启软件</Typography.Text>
                生效；换端口后浏览器插件弹窗里的「服务地址」也要同步改成
                <Typography.Text code>http://127.0.0.1:新端口</Typography.Text>
              </span>
            }
            style={{ marginBottom: 0 }}
          >
            <InputNumber min={1024} max={65535} style={{ width: 160 }} />
          </Form.Item>
        </Card>

        <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={save.isPending}>
          保存设置
        </Button>
      </Form>

      <Card title="外观" style={{ marginBottom: 16 }}>
        <Radio.Group
          optionType="button"
          buttonStyle="solid"
          value={themeMode}
          onChange={(e) => setThemeMode(e.target.value as ThemeMode)}
          options={THEME_OPTIONS}
        />
        <div style={{ marginTop: 8 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            深色模式即时生效；「跟随系统」会随 Windows 主题自动切换。插件弹窗跟随系统外观。
          </Typography.Text>
        </div>
      </Card>

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
          <Descriptions.Item label="当前监听端口">{data?.port ?? '—'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="关于">
        <Typography.Paragraph>
          AutoOffer —— 通用简历自动填写智能体。数据全部保存在本机，仅向您配置的模型端点发送数据。
          填写结果需人工审核后自行提交，请遵守目标网站服务条款。
        </Typography.Paragraph>
      </Card>
    </Space>
  );
}
