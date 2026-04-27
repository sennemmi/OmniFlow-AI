import '@testing-library/jest-dom';
import { vi, beforeAll, afterEach, afterAll } from 'vitest';
import { server } from '../mocks/server';

// 启动 MSW
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Mock Monaco Editor
vi.mock('@monaco-editor/react', () => ({
  default: function MonacoEditor({ value }: { value: string }) {
    return null;
  },
  Editor: function Editor({ value }: { value: string }) {
    return null;
  },
}));

// Mock React Flow
vi.mock('@xyflow/react', () => ({
  ReactFlow: function ReactFlow({ children }: { children: React.ReactNode }) {
    return null;
  },
  Background: function Background() {
    return null;
  },
  Controls: function Controls() {
    return null;
  },
  useNodesState: () => [[], vi.fn()],
  useEdgesState: () => [[], vi.fn()],
}));

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
