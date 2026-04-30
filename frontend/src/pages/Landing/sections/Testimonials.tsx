import { Award, Sparkles } from 'lucide-react';
import { testimonials } from '../data';

export function Testimonials() {
  return (
    <section className="py-24">
      <div className="container-feishu">
        <div className="text-center max-w-3xl mx-auto mb-16 animate-on-scroll">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-brand-primary/10 text-brand-primary text-sm font-medium mb-6">
            <Award className="w-4 h-4" />
            客户评价
          </div>
          <h2 className="text-4xl lg:text-5xl font-bold text-text-primary mb-6">
            深受企业信赖
          </h2>
          <p className="text-text-secondary text-lg">
            超过 500 家企业选择 OmniFlowAI 提升研发效率
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-8">
          {testimonials.map((testimonial, index) => (
            <div
              key={index}
              className="p-8 rounded-2xl bg-bg-primary border border-border-default shadow-feishu-card animate-on-scroll"
              style={{ transitionDelay: `${index * 100}ms` }}
            >
              <div className="flex gap-1 mb-6">
                {[...Array(5)].map((_, i) => (
                  <Sparkles key={i} className="w-5 h-5 text-yellow-400 fill-yellow-400" />
                ))}
              </div>
              <p className="text-text-primary text-lg leading-relaxed mb-6">
                &ldquo;{testimonial.content}&rdquo;
              </p>
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-full bg-brand-primary/10 flex items-center justify-center">
                  <span className="text-brand-primary font-semibold">
                    {testimonial.author[0]}
                  </span>
                </div>
                <div>
                  <p className="font-semibold text-text-primary">{testimonial.author}</p>
                  <p className="text-sm text-text-tertiary">
                    {testimonial.role} · {testimonial.company}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
