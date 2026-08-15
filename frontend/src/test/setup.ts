/**
 * 测试环境初始化：polyfill jsdom 缺失的浏览器 API，并挂载 jest-dom 匹配器。
 * antd v5 的响应式组件依赖 matchMedia / ResizeObserver。
 */
import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// antd Grid/Col 等响应式组件在 jsdom 下需要 matchMedia
if (!window.matchMedia) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

// antd Table/Statistic 等可能用到 ResizeObserver
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

// jsdom 未实现 Element.scrollTo（任务详情页滚动事件流用）
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo() {};
}

afterEach(() => {
  cleanup();
});
