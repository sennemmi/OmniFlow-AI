import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Zap, Menu, X, ChevronRight } from 'lucide-react';
import { useUIStore } from '@stores/uiStore';

// ============================================
// 飞书风格导航栏 - 毛玻璃效果
// ============================================

const navItems = [
  { label: '首页', path: '/' },
  { label: '控制台', path: '/console' },
  { label: '文档', path: '/docs' },
];

export function Navbar() {
  const location = useLocation();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const { isNavbarScrolled, setNavbarScrolled } = useUIStore();

  // 监听滚动
  useEffect(() => {
    const handleScroll = () => {
      setNavbarScrolled(window.scrollY > 20);
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [setNavbarScrolled]);

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/';
    }
    return location.pathname.startsWith(path);
  };

  return (
    <header
      className={`fixed top-0 left-0 right-0 h-16 z-50 transition-all duration-300 ${
        isNavbarScrolled
          ? 'bg-bg-primary/90 backdrop-blur-xl shadow-feishu-card border-b border-border-default/50'
          : 'bg-transparent'
      }`}
    >
      <div className="container-feishu h-full flex items-center justify-between">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2 group">
          <div className="w-9 h-9 rounded-lg bg-brand-primary flex items-center justify-center transition-transform duration-300 group-hover:scale-105">
            <Zap className="w-5 h-5 text-text-white" />
          </div>
          <span
            className={`text-lg font-semibold transition-colors duration-300 ${
              isNavbarScrolled ? 'text-text-primary' : 'text-text-white'
            }`}
          >
            OmniFlowAI
          </span>
        </Link>

        {/* Desktop Navigation */}
        <nav className="hidden md:flex items-center gap-1">
          {navItems.map((item) => (
            <Link
              key={item.path}
              to={item.path}
              className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 ${
                isActive(item.path)
                  ? isNavbarScrolled
                    ? 'text-brand-primary bg-brand-primary-light'
                    : 'text-text-white bg-text-white/10'
                  : isNavbarScrolled
                  ? 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
                  : 'text-text-white/80 hover:text-text-white hover:bg-text-white/10'
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        {/* CTA Button */}
        <div className="hidden md:flex items-center gap-3">
          <Link
            to="/console"
            className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-sm font-medium transition-all duration-250 ${
              isNavbarScrolled
                ? 'bg-brand-primary text-text-white hover:bg-brand-primary-hover hover:-translate-y-0.5 hover:shadow-feishu-button'
                : 'bg-text-white text-brand-primary hover:bg-text-white/90 hover:-translate-y-0.5'
            }`}
          >
            开始使用
            <ChevronRight className="w-4 h-4" />
          </Link>
        </div>

        {/* Mobile Menu Button */}
        <button
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className={`md:hidden p-2 rounded-md transition-colors ${
            isNavbarScrolled
              ? 'text-text-primary hover:bg-bg-secondary'
              : 'text-text-white hover:bg-text-white/10'
          }`}
        >
          {isMobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Mobile Menu */}
      {isMobileMenuOpen && (
        <div className="md:hidden absolute top-16 left-0 right-0 bg-bg-primary border-b border-border-default shadow-feishu">
          <nav className="container-feishu py-4 flex flex-col gap-1">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => setIsMobileMenuOpen(false)}
                className={`px-4 py-3 rounded-md text-sm font-medium transition-colors ${
                  isActive(item.path)
                    ? 'text-brand-primary bg-brand-primary-light'
                    : 'text-text-secondary hover:text-text-primary hover:bg-bg-secondary'
                }`}
              >
                {item.label}
              </Link>
            ))}
            <Link
              to="/console"
              onClick={() => setIsMobileMenuOpen(false)}
              className="mt-2 px-4 py-3 bg-brand-primary text-text-white rounded-lg text-sm font-medium text-center hover:bg-brand-primary-hover"
            >
              开始使用
            </Link>
          </nav>
        </div>
      )}
    </header>
  );
}