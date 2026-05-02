import { useEffect } from 'react';
import { Navbar } from '@components/Layout';
import {
  Hero,
  Stats,
  Features,
  Modules,
  Testimonials,
  Pricing,
  CTA,
  Footer,
} from './Landing/sections';

export function Landing() {
  // 滚动动画
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible');
          }
        });
      },
      { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
    );

    document.querySelectorAll('.animate-on-scroll').forEach((el) => {
      observer.observe(el);
    });

    return () => observer.disconnect();
  }, []);

  return (
    <div className="min-h-screen bg-bg-secondary">
      <Navbar />
      <Hero />
      <Stats />
      <Features />
      <Modules />
      <Testimonials />
      <Pricing />
      <CTA />
      <Footer />
    </div>
  );
}
