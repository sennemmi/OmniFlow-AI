import { Layers } from 'lucide-react';
import { modules } from '../data';

export function Modules() {
  return (
    <section className="py-24 bg-bg-primary">
      <div className="container-feishu">
        <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
            <Layers className="w-4 h-4" />
            功能模块
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
            覆盖研发全流程
          </h2>
          <p className="text-text-secondary text-lg">
            从架构设计到生产部署，提供完整的企业级研发工具链
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {modules.map((module, index) => {
            const Icon = module.icon;
            return (
              <div
                key={module.title}
                className="group p-8 rounded-2xl bg-bg-secondary border border-border-default hover:border-brand-primary/30 hover:shadow-xl hover:shadow-brand-primary/5 transition-all duration-300 animate-on-scroll"
                style={{ transitionDelay: `${index * 50}ms` }}
              >
                <div className="w-14 h-14 rounded-2xl bg-brand-primary/10 flex items-center justify-center mb-6 group-hover:bg-brand-primary group-hover:scale-110 transition-all duration-300">
                  <Icon className="w-7 h-7 text-brand-primary group-hover:text-white transition-colors" />
                </div>
                <h3 className="text-xl font-semibold text-text-primary mb-3">{module.title}</h3>
                <p className="text-text-secondary mb-6 leading-relaxed">{module.description}</p>
                <div className="flex flex-wrap gap-2">
                  {module.features.map((feature) => (
                    <span
                      key={feature}
                      className="px-3 py-1 rounded-full bg-bg-tertiary text-text-secondary text-xs"
                    >
                      {feature}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
