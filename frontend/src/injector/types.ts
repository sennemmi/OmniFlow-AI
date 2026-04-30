/**
 * OmniFlowAI Injector - TypeScript 类型定义
 * 定义所有事件类型和接口
 */

// ============================================
// 元素信息接口
// ============================================
export interface ElementRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ReactDebugInfo {
  hasFiber: boolean;
  componentName: string | null;
  sourceLocation: {
    fileName: string;
    lineNumber: number;
    columnNumber: number;
  } | null;
}

export interface ElementInfo {
  tag: string;
  id: string;
  class: string;
  text: string;
  outerHTML: string;
  xpath: string;
  selector: string;
  props: Record<string, string>;
  componentName: string;
  sourceFile: string;
  sourceLine: number;
  sourceColumn: number;
  dataSource: string;
  dataComponent: string;
  dataFile: string;
  reactDebugInfo: ReactDebugInfo | null;
  rect: ElementRect;
}

// ============================================
// 配置接口
// ============================================
export interface Config {
  API_BASE_URL: string;
  API_ENDPOINT: string;
  POLL_INTERVAL: number;
  ICON_SIZE: number;
  Z_INDEX: number;
  COLORS: {
    primary: string;
    highlight: string;
    border: string;
    overlay: string;
    success: string;
    warning: string;
    error: string;
    selection: string;
    selectionBorder: string;
  };
}

// ============================================
// 状态接口
// ============================================
export interface AppState {
  isActive: boolean;
  isSelectionMode: boolean;
  selectedElement: HTMLElement | null;
  selectedElements: HTMLElement[];
  hoverElement: HTMLElement | null;
  currentPipelineId: string | null;
  isPolling: boolean;
  floatingPanel: HTMLElement | null;
  editDialog: HTMLElement | null;
}

// ============================================
// API 响应接口
// ============================================
export interface PipelineResponse {
  success: boolean;
  data?: {
    pipeline_id: string;
    status: string;
    current_stage_index: number;
    stages: string[];
    delivery?: {
      pr_url: string;
    };
  };
  error?: string;
}

export interface FileContentResponse {
  success: boolean;
  data?: {
    content: string;
    path: string;
  };
  error?: string;
}

export interface ModifyResponse {
  success: boolean;
  data?: {
    new_content: string;
    diff: string;
  };
  error?: string;
}

export interface BatchModifyResponse {
  success: boolean;
  data?: {
    success_files: number;
    failed_files: number;
    results: Array<{
      file: string;
      success: boolean;
      error?: string;
    }>;
  };
  error?: string;
}

// ============================================
// 预览状态接口
// ============================================
export interface PreviewState {
  isPreviewing: boolean;
  filePath: string | null;
  originalContent: string | null;
  modifiedContent: string | null;
  previewBanner: HTMLElement | null;
  escHandler: ((e: KeyboardEvent) => void) | null;
}

// ============================================
// 事件类型定义 (用于类型安全的事件总线)
// ============================================
export interface OmniEvents {
  // 模式切换事件
  'mode:selection:toggle': { active: boolean };
  'mode:selection:enter': void;
  'mode:selection:exit': void;

  // 元素交互事件
  'element:hover': { element: HTMLElement | null };
  'element:click': { element: HTMLElement; isShift: boolean };
  'element:select:single': { element: HTMLElement; elementInfo: ElementInfo };
  'element:select:multi': { elements: HTMLElement[] };
  'element:deselect:all': void;

  // 业务动作事件
  'action:modify:submit': { elementInfo: ElementInfo; feedback: string };
  'action:area-modify:submit': { elements: HTMLElement[]; feedback: string };
  'action:preview:start': { elementInfo: ElementInfo; feedback: string };
  'action:preview:confirm': { filePath: string };
  'action:preview:cancel': { filePath: string; originalContent: string };

  // Pipeline 事件
  'pipeline:created': { pipelineId: string };
  'pipeline:progress': { status: string; percent: number };
  'pipeline:completed': { success: boolean; prUrl?: string };
  'pipeline:error': { error: string };

  // UI 状态事件
  'ui:toast': { message: string; type: 'info' | 'success' | 'error' | 'warning' };
  'ui:progress:show': { pipelineId?: string };
  'ui:progress:update': { status: string; percent: number };
  'ui:progress:hide': void;
  'ui:dialog:show': { element: HTMLElement; elementInfo: ElementInfo; isMulti?: boolean };
  'ui:dialog:close': void;
  'ui:panel:show': { elements: HTMLElement[] };
  'ui:panel:close': void;
  'ui:notification:show': { prUrl: string };
  'ui:preview-controls:show': { filePath: string; originalContent: string };
  'ui:preview-controls:hide': void;

  // 系统事件
  'system:init': void;
  'system:error': { error: Error };
}

// ============================================
// 事件处理器类型
// ============================================
export type EventHandler<T = unknown> = (data: T) => void | Promise<void>;

// ============================================
// 模块接口
// ============================================
export interface IModule {
  init(): void | Promise<void>;
  destroy?(): void | Promise<void>;
}

// ============================================
// DOM 工具接口
// ============================================
export interface IDOMUtils {
  create(tag: string, className?: string, styles?: Partial<CSSStyleDeclaration>): HTMLElement;
  getElementInfo(el: HTMLElement): ElementInfo;
  getElementsInRect(rect: DOMRect): HTMLElement[];
  getSurroundingContext(elementInfo: ElementInfo): Record<string, unknown>;
}

export interface IUtils {
  getXPath(el: HTMLElement): string;
  getUniqueSelector(el: HTMLElement): string;
  isOmniElement(el: HTMLElement | EventTarget | null): boolean;
  escapeHtml(html: string): string;
  calculatePanelPosition(referenceRect: DOMRect, panel: HTMLElement): { x: number; y: number };
}

// ============================================
// React Source Mapper 接口
// ============================================
export interface IReactSourceMapper {
  isDevToolsAvailable(): boolean;
  getFiberNode(element: HTMLElement): unknown | null;
  getComponentNameFromFiber(fiber: unknown): string | null;
  getSourceLocationFromFiber(fiber: unknown): { fileName: string; lineNumber: number; columnNumber: number } | null;
  getComponentInfo(element: HTMLElement): ReactDebugInfo | null;
}
