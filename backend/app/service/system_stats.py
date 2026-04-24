import psutil

from app.models.stats_response import SystemStatsSchema


class SystemStatsService:
    @staticmethod
    def collect_stats():
        cpu_usage = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        memory_usage = memory.percent
        return SystemStatsSchema(cpu_usage=cpu_usage, memory_usage=memory_usage)