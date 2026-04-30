import { create } from 'zustand';

// ============================================
// UI 状态管理 (Zustand)
// ============================================

interface UIState {
  // 导航栏滚动状态
  isNavbarScrolled: boolean;
  
  // 侧边栏折叠状态
  isSidebarCollapsed: boolean;
  
  // 全局加载状态
  isGlobalLoading: boolean;
  
  // Toast 通知
  toasts: ToastItem[];
  
  // Actions
  setNavbarScrolled: (scrolled: boolean) => void;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  setGlobalLoading: (loading: boolean) => void;
  addToast: (toast: Omit<ToastItem, 'id'>) => void;
  removeToast: (id: string) => void;
}

interface ToastItem {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  duration?: number;
}

export const useUIStore = create<UIState>((set, get) => ({
  isNavbarScrolled: false,
  isSidebarCollapsed: false,
  isGlobalLoading: false,
  toasts: [],
  
  setNavbarScrolled: (scrolled) => set({ isNavbarScrolled: scrolled }),
  
  toggleSidebar: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed })),
  
  setSidebarCollapsed: (collapsed) => set({ isSidebarCollapsed: collapsed }),
  
  setGlobalLoading: (loading) => set({ isGlobalLoading: loading }),
  
  addToast: (toast) => {
    const id = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const newToast: ToastItem = { ...toast, id, duration: toast.duration || 3000 };
    set((state) => ({ toasts: [...state.toasts, newToast] }));
    
    // 自动移除
    setTimeout(() => {
      get().removeToast(id);
    }, newToast.duration);
  },
  
  removeToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((t) => t.id !== id),
    }));
  },
}));
