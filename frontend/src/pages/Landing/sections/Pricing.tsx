import { Link } from 'react-router-dom';
import { Zap, CheckCircle2 } from 'lucide-react';
import { pricingPlans } from '../data';

export function Pricing() {
  return (
    <section className="py-24 bg-bg-primary">
      <div className="container-feishu">
        <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
            <Zap className="w-4 h-4" />
            定价方案
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
            选择适合您的方案
          </h2>
          <p className="text-text-secondary text-lg">
            从免费开始，随业务增长灵活升级
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-8 max-w-6xl mx-auto">
          {pricingPlans.map((plan, index) => (
            <div
              key={plan.name}
              className={`relative p-8 rounded-2xl border-2 transition-all duration-300 animate-on-scroll ${
                plan.popular
                  ? 'border-brand-primary bg-brand-primary/5 shadow-xl shadow-brand-primary/10 scale-105'
                  : 'border-border-default bg-bg-secondary hover:border-brand-primary/30'
              }`}
              style={{ transitionDelay: `${index * 100}ms` }}
            >
              {plan.popular && (
                <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full bg-brand-primary text-white text-sm font-medium">
                  最受欢迎
                </div>
              )}
              <div className="text-center mb-8">
                <h3 className="text-xl font-semibold text-text-primary mb-2">{plan.name}</h3>
                <p className="text-text-secondary text-sm mb-6">{plan.description}</p>
                <div className="flex items-baseline justify-center gap-1">
                  <span className="text-2xl text-text-tertiary">¥</span>
                  <span className="text-5xl font-bold text-text-primary">{plan.price}</span>
                  <span className="text-text-tertiary">{plan.period}</span>
                </div>
              </div>
              <ul className="space-y-4 mb-8">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-center gap-3">
                    <CheckCircle2 className={`w-5 h-5 ${plan.popular ? 'text-brand-primary' : 'text-text-tertiary'}`} />
                    <span className="text-text-secondary">{feature}</span>
                  </li>
                ))}
              </ul>
              <Link
                to="/console"
                className={`block w-full py-3 rounded-xl text-center font-semibold transition-all duration-300 ${
                  plan.popular
                    ? 'bg-brand-primary text-white hover:bg-brand-primary-hover shadow-lg shadow-brand-primary/25'
                    : 'bg-bg-tertiary text-text-primary hover:bg-border-default'
                }`}
              >
                {plan.cta}
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
