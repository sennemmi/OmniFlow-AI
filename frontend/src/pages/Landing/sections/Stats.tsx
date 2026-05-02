import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@utils/axios';
import { stats } from '../data';

export function Stats() {
  const { data: realStats } = useQuery({
    queryKey: ['system-stats'],
    queryFn: () => apiGet('/system/stats'),
  });

  return (
    <section className="py-20 bg-bg-primary border-y border-border-default">
      <div className="container-feishu">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-8">
          {stats.map((stat, index) => {
            const Icon = stat.icon;
            return (
              <div
                key={stat.label}
                className="text-center animate-on-scroll group"
                style={{ transitionDelay: `${index * 100}ms` }}
              >
                <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-brand-primary/10 mb-4 group-hover:bg-brand-primary/20 transition-colors">
                  <Icon className="w-7 h-7 text-brand-primary" />
                </div>
                <div className="text-4xl lg:text-5xl font-bold text-red-500 mb-2">
                  {realStats ? (
                    index === 0 ? realStats.total_pipelines || 0 :
                    index === 1 ? (realStats.avg_duration || 0) :
                    index === 2 ? '99.9' :
                    index === 3 ? '500+' : stat.value
                  ) : stat.value}
                  <span className="text-2xl text-red-500">{stat.suffix}</span>
                </div>
                <p className="text-text-secondary">{stat.label}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
