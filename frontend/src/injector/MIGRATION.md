# OmniFlowAI Injector 重构迁移指南

## 概述

本次重构将原有的纯 JavaScript IIFE 模式 Injector 改造为 TypeScript + 事件驱动架构，解决了以下问题：

1. **硬依赖问题**：消除了 `Handlers.setCallbacks()` 的强耦合
2. **加载顺序问题**：不再需要严格维护脚本加载顺序
3. **命名空间污染**：不再污染全局 `window` 对象
4. **类型安全**：增加了 TypeScript 类型检查

## 架构对比

### 重构前（IIFE 模式）

```javascript
// main.js - 强耦合
Handlers.setCallbacks({
  onHandleModify: (elementInfo, feedback) => {
    Pipeline.quickModify(elementInfo, feedback, () => {
      VisualFeedback.closeEditDialog();
      exitSelectionMode();
    });
  },
});
```

### 重构后（事件驱动）

```typescript
// interaction.ts - 只负责 emit 事件
bus.emit('element:click', { element: el, isShift: e.shiftKey });

// pipeline.ts - 监听事件并处理
bus.on('action:modify:submit', async ({ elementInfo, feedback }) => {
  await this.handleQuickModify(elementInfo, feedback);
});
```

## 文件结构变化

### 重构前
```
public/
├── injector.js          # 加载器
└── injector/
    ├── config.js
    ├── core.js
    ├── api.js
    ├── ui.js
    ├── state.js
    ├── selection.js
    ├── handlers.js      # 通过回调耦合
    ├── preview.js
    └── pipeline.js      # 被 main.js 直接调用
```

### 重构后
```
src/injector/            # 纳入 src，参与 Vite 构建
├── index.ts            # 统一入口
├── types.ts            # 类型定义
├── events.ts           # 事件总线
├── config.ts           # 配置
├── core.ts             # DOM 工具
├── api.ts              # API 客户端
├── state.ts            # 状态管理
├── ui.ts               # UI 组件
├── selection.ts        # 视觉反馈
├── interaction.ts      # 交互处理（原 handlers.js）
├── pipeline.ts         # Pipeline 逻辑
├── preview.ts          # 预览功能
└── styles.css          # 样式

public/
└── omni-injector.iife.js  # 构建产物
```

## 事件总线 API

### 基本用法

```typescript
import { bus, Events } from '@injector';

// 监听事件
const unsubscribe = bus.on('element:click', ({ element, isShift }) => {
  console.log('元素被点击:', element);
});

// 触发事件
bus.emit('element:click', { element: el, isShift: false });

// 取消监听
unsubscribe();
```

### 事件列表

#### 模式切换
- `mode:selection:toggle` - 切换选择模式
- `mode:selection:enter` - 进入选择模式
- `mode:selection:exit` - 退出选择模式

#### 元素交互
- `element:hover` - 鼠标悬停元素
- `element:click` - 点击元素
- `element:select:single` - 单选元素
- `element:select:multi` - 多选元素
- `element:deselect:all` - 取消所有选择

#### 业务动作
- `action:modify:submit` - 提交修改
- `action:area-modify:submit` - 批量修改
- `action:preview:start` - 开始预览
- `action:preview:confirm` - 确认预览
- `action:preview:cancel` - 取消预览

#### Pipeline
- `pipeline:created` - Pipeline 创建成功
- `pipeline:progress` - Pipeline 进度更新
- `pipeline:completed` - Pipeline 完成
- `pipeline:error` - Pipeline 错误

#### UI 状态
- `ui:toast` - 显示 Toast
- `ui:progress:show` - 显示进度条
- `ui:progress:update` - 更新进度条
- `ui:progress:hide` - 隐藏进度条
- `ui:dialog:show` - 显示对话框
- `ui:dialog:close` - 关闭对话框

## 模块职责

### interaction.ts（原 handlers.js）
- **职责**：监听原生 DOM 事件，转换为内部事件
- **不处理**：任何业务逻辑

### pipeline.ts
- **职责**：处理 AI 修改逻辑，调用 API
- **监听**：`action:modify:submit`, `action:area-modify:submit`

### ui.ts
- **职责**：渲染 UI 组件
- **监听**：`ui:toast`, `ui:progress:*`, `ui:dialog:*`

### selection.ts
- **职责**：管理视觉反馈（高亮、多选框）
- **方法**：`visualFeedback.highlightElement()`, `panelManager.showAreaSelectionPanel()`

## 全局 API（向后兼容）

重构后仍然暴露 `window.OmniFlowAI` 对象：

```javascript
// 公共 API
OmniFlowAI.toggle();      // 切换选择模式
OmniFlowAI.enter();       // 进入选择模式
OmniFlowAI.exit();        // 退出选择模式
OmniFlowAI.isActive();    // 是否处于选择模式
OmniFlowAI.version;       // 版本号

// 工具方法
OmniFlowAI.getElementInfo(element);  // 获取元素信息

// 事件总线（高级用法）
OmniFlowAI.events.on(event, handler);
OmniFlowAI.events.off(event, handler);
OmniFlowAI.events.emit(event, data);
```

## 构建配置

### vite.config.ts

```typescript
build: {
  rollupOptions: {
    input: {
      main: path.resolve(__dirname, 'index.html'),
      injector: path.resolve(__dirname, 'src/injector/index.ts'),
    },
    output: {
      entryFileNames: (chunkInfo) => {
        if (chunkInfo.name === 'injector') {
          return 'omni-injector.iife.js'
        }
        return 'assets/[name]-[hash].js'
      },
      format: 'iife',
    },
  },
}
```

## 迁移步骤

1. **备份原有文件**
   ```bash
   mv public/injector public/injector-backup
   mv public/injector.js public/injector.js.backup
   ```

2. **构建项目**
   ```bash
   npm run build
   ```

3. **验证构建产物**
   - 检查 `dist/omni-injector.iife.js` 是否存在

4. **更新 HTML 引用**
   ```html
   <!-- 旧方式 -->
   <script src="/injector.js" data-api-url="http://localhost:8000"></script>
   
   <!-- 新方式 -->
   <script src="/omni-injector.iife.js" data-api-url="http://localhost:8000"></script>
   ```

5. **功能验证**
   - 点击浮动图标进入选择模式
   - 点击页面元素
   - 输入修改指令
   - 验证 AI 预览和确认流程

## 优势总结

1. **解耦**：模块间通过事件通信，无直接依赖
2. **类型安全**：TypeScript 提供编译时类型检查
3. **可测试性**：可以单独测试每个模块的事件响应
4. **可扩展性**：新增功能只需添加新的事件类型
5. **构建优化**：Vite 打包，代码压缩，单文件加载

## 注意事项

1. 事件名称使用常量定义，避免魔术字符串
2. 监听事件后记得取消监听，避免内存泄漏
3. 事件处理器中的错误会被自动捕获并打印
4. 状态变更通过 `stateManager` 统一管理
