import { beforeEach, describe, expect, it, vi } from 'vitest';
import { screen } from '@testing-library/react';
import TaskDetail from './TaskDetail';
import { renderWithProviders } from '../test/renderWithProviders';

vi.mock('../api/ws', () => ({
  useTaskStream: vi.fn(),
}));

vi.mock('../api/client', () => ({
  getTask: vi.fn(),
}));

import { getTask } from '../api/client';
import { useTaskStream } from '../api/ws';

const getTaskMock = getTask as ReturnType<typeof vi.fn>;
const useTaskStreamMock = useTaskStream as ReturnType<typeof vi.fn>;

const BASE_TASK = {
  id: 'task-1',
  url: 'https://example.com/apply',
  profile_id: 'p1',
  state: 'DONE' as const,
  page_title: '示例公司 - 招聘',
  wait_reason: '',
  report: null,
  created_at: '2026-08-15T10:00:00',
  updated_at: '2026-08-15T10:05:00',
};

describe('TaskDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTaskStreamMock.mockReturnValue({ events: [], connState: 'closed', liveState: null });
  });

  it('渲染任务详情与等待审核状态', async () => {
    getTaskMock.mockResolvedValue({ ...BASE_TASK, state: 'AWAITING_REVIEW' });

    renderWithProviders(
      <TaskDetail taskId="task-1" onResume={() => {}} onCancel={() => {}} onChanged={() => {}} />,
    );

    expect(await screen.findByText('任务详情')).toBeInTheDocument();
    expect(await screen.findByText('示例公司 - 招聘')).toBeInTheDocument();
    expect(await screen.findByText('等待审核')).toBeInTheDocument();
  });

  it('渲染填写报告统计与字段状态', async () => {
    getTaskMock.mockResolvedValue({
      ...BASE_TASK,
      report: {
        task_id: 'task-1',
        url: 'https://example.com/apply',
        page_title: '示例公司 - 招聘',
        profile_id: 'p1',
        fields: [
          {
            label: '姓名',
            status: 'filled',
            value: '张三',
            attempts: 1,
            note: null,
            sensitive: false,
          },
          {
            label: '期望薪资',
            status: 'pending_confirm',
            value: null,
            attempts: 1,
            note: '档案缺失',
            sensitive: false,
          },
        ],
        started_at: '2026-08-15T10:00:00',
        finished_at: '2026-08-15T10:05:00',
        total_llm_calls: 10,
        total_tokens: 1000,
        note: null,
      },
    });

    renderWithProviders(
      <TaskDetail taskId="task-1" onResume={() => {}} onCancel={() => {}} onChanged={() => {}} />,
    );

    expect(await screen.findByText('姓名')).toBeInTheDocument();
    // 「已填写」/「待确认」同时出现在统计卡片标题与字段状态标签中，改用 findAllByText 断言
    const filledTags = await screen.findAllByText('已填写');
    expect(filledTags.length).toBeGreaterThanOrEqual(2);
    const pendingTags = await screen.findAllByText('待确认');
    expect(pendingTags.length).toBeGreaterThanOrEqual(2);
  });
});
