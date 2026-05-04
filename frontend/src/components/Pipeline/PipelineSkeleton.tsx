/**
 * Pipeline 详情页骨架屏
 * 优化加载体验，减少用户等待感知
 */

export function PipelineSkeleton() {
  return (
    <div className="h-full flex flex-col animate-pulse">
      {/* 头部骨架 */}
      <div className="flex items-center justify-between mb-4 pb-4 border-b border-slate-200">
        <div className="flex items-center gap-4">
          {/* 返回按钮 */}
          <div className="w-9 h-9 rounded-lg bg-slate-200" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-3">
              {/* Pipeline ID */}
              <div className="h-7 w-32 bg-slate-200 rounded" />
              {/* 状态标签 */}
              <div className="h-6 w-20 bg-slate-200 rounded-full" />
            </div>
            {/* 描述 */}
            <div className="h-4 w-64 bg-slate-200 rounded mt-2" />
          </div>
        </div>

        {/* 操作按钮组 */}
        <div className="flex items-center gap-2">
          <div className="w-[100px] h-10 bg-slate-200 rounded-lg" />
          <div className="w-10 h-10 bg-slate-200 rounded-lg" />
          <div className="w-10 h-10 bg-slate-200 rounded-lg" />
        </div>
      </div>

      {/* 主内容区骨架 */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* 左侧：流程图区域 */}
        <div className="flex-[2] bg-white rounded-xl border border-slate-200 overflow-hidden shadow-sm">
          <div className="h-full flex items-center justify-center">
            <div className="flex flex-col items-center gap-4">
              {/* 流程图节点骨架 */}
              <div className="flex items-center gap-8">
                <div className="w-32 h-20 bg-slate-200 rounded-lg" />
                <div className="w-16 h-0.5 bg-slate-200" />
                <div className="w-32 h-20 bg-slate-200 rounded-lg" />
                <div className="w-16 h-0.5 bg-slate-200" />
                <div className="w-32 h-20 bg-slate-200 rounded-lg" />
              </div>
              <div className="flex items-center gap-8 mt-4">
                <div className="w-32 h-20 bg-slate-200 rounded-lg" />
                <div className="w-16 h-0.5 bg-slate-200" />
                <div className="w-32 h-20 bg-slate-200 rounded-lg" />
                <div className="w-16 h-0.5 bg-slate-200" />
                <div className="w-32 h-20 bg-slate-200 rounded-lg" />
              </div>
            </div>
          </div>
        </div>

        {/* 右侧：终端区域 */}
        <div className="w-96 flex-shrink-0 min-h-0 h-full bg-slate-900 rounded-xl">
          <div className="p-4">
            <div className="h-4 w-24 bg-slate-700 rounded mb-4" />
            <div className="space-y-2">
              <div className="h-3 w-full bg-slate-700 rounded" />
              <div className="h-3 w-4/5 bg-slate-700 rounded" />
              <div className="h-3 w-3/4 bg-slate-700 rounded" />
              <div className="h-3 w-5/6 bg-slate-700 rounded" />
              <div className="h-3 w-2/3 bg-slate-700 rounded" />
            </div>
          </div>
        </div>
      </div>

      {/* 底部信息栏骨架 */}
      <div className="mt-4 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
        <div className="flex items-center gap-6">
          {/* 当前阶段 */}
          <div className="flex items-center gap-3 min-w-[140px]">
            <div className="w-9 h-9 rounded-lg bg-slate-200" />
            <div>
              <div className="h-3 w-16 bg-slate-200 rounded mb-1" />
              <div className="h-4 w-20 bg-slate-200 rounded" />
            </div>
          </div>

          <div className="w-px h-8 bg-slate-200" />

          {/* 进度 */}
          <div className="flex flex-col gap-2 flex-1 max-w-[240px]">
            <div className="flex items-center justify-between">
              <div className="h-3 w-8 bg-slate-200 rounded" />
              <div className="h-3 w-16 bg-slate-200 rounded" />
            </div>
            <div className="h-2 w-full bg-slate-200 rounded-full" />
          </div>

          <div className="w-px h-8 bg-slate-200" />

          {/* 创建时间 */}
          <div className="flex items-center gap-3 min-w-[160px]">
            <div className="w-9 h-9 rounded-lg bg-slate-200" />
            <div>
              <div className="h-3 w-16 bg-slate-200 rounded mb-1" />
              <div className="h-4 w-24 bg-slate-200 rounded" />
            </div>
          </div>

          <div className="w-px h-8 bg-slate-200" />

          {/* 更新时间 */}
          <div className="flex items-center gap-3 min-w-[160px]">
            <div className="w-9 h-9 rounded-lg bg-slate-200" />
            <div>
              <div className="h-3 w-16 bg-slate-200 rounded mb-1" />
              <div className="h-4 w-24 bg-slate-200 rounded" />
            </div>
          </div>

          <div className="flex-1" />

          {/* 阶段完成数 */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-200 rounded-lg flex-shrink-0">
            <div className="h-3 w-12 bg-slate-300 rounded" />
            <div className="h-4 w-8 bg-slate-300 rounded" />
            <div className="h-3 w-12 bg-slate-300 rounded" />
          </div>
        </div>
      </div>

      {/* 阶段执行指标骨架 */}
      <div className="mt-4 bg-white rounded-xl border border-slate-200 p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3">
          <div className="h-4 w-24 bg-slate-200 rounded" />
          <div className="h-3 w-16 bg-slate-200 rounded" />
        </div>
        
        <div className="grid grid-cols-5 gap-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="p-3 rounded-lg border border-slate-200 bg-slate-50">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-7 h-7 rounded-md bg-slate-200" />
                <div className="flex-1 min-w-0">
                  <div className="h-3 w-16 bg-slate-200 rounded" />
                </div>
                <div className="h-4 w-10 bg-slate-200 rounded-full" />
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <div className="h-2 w-8 bg-slate-200 rounded" />
                  <div className="h-3 w-10 bg-slate-200 rounded" />
                </div>
                <div className="flex items-center justify-between">
                  <div className="h-2 w-8 bg-slate-200 rounded" />
                  <div className="h-3 w-10 bg-slate-200 rounded" />
                </div>
                <div className="flex items-center justify-between">
                  <div className="h-2 w-8 bg-slate-200 rounded" />
                  <div className="h-3 w-10 bg-slate-200 rounded" />
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
