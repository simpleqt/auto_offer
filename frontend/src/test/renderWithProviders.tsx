import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactElement, ReactNode } from 'react';
import { App as AntApp, ConfigProvider } from 'antd';

/** 用真实 QueryClient 包裹组件渲染（配合 vi.mock 掉 api/client 返回 mock 数据）。 */
export function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ConfigProvider>
        <AntApp>
          <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        </AntApp>
      </ConfigProvider>
    );
  }

  return render(ui, { wrapper: Wrapper });
}
