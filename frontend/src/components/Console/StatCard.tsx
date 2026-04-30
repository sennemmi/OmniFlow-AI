interface StatCardProps {
  title: string;
  value: string;
  trend?: string;
  icon: React.ComponentType<{ className?: string }>;
}

export function StatCard({ title, value, trend, icon: Icon }: StatCardProps) {
  return (
    <div className="card-flat p-6">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-text-secondary mb-1">{title}</p>
          <p className="text-2xl font-bold text-text-primary">{value}</p>
          {trend && <p className="text-xs text-status-success mt-1">{trend}</p>}
        </div>
        <div className="w-10 h-10 rounded-xl bg-brand-primary-light flex items-center justify-center">
          <Icon className="w-5 h-5 text-brand-primary" />
        </div>
      </div>
    </div>
  );
}
