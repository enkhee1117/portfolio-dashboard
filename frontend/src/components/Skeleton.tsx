"use client";

export function SkeletonCard({ rows = 3 }: { rows?: number }) {
  return (
    <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg animate-pulse">
      <div className="h-4 bg-gray-700 rounded w-1/3 mb-4" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-3 bg-gray-700 rounded w-full mb-2" />
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 shadow-lg overflow-hidden animate-pulse">
      <div className="bg-gray-900/50 px-4 py-3 flex gap-4">
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className="h-3 bg-gray-700 rounded flex-1" />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="px-4 py-3 flex gap-4 border-t border-gray-700">
          {Array.from({ length: cols }).map((_, j) => (
            <div key={j} className="h-3 bg-gray-700/60 rounded flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonDashboard() {
  return (
    <div className="space-y-6">
      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-gray-800 rounded-xl p-5 border border-gray-700 animate-pulse">
            <div className="h-3 bg-gray-700 rounded w-1/2 mb-3" />
            <div className="h-6 bg-gray-700 rounded w-3/4" />
          </div>
        ))}
      </div>
      {/* Chart */}
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 animate-pulse">
        <div className="h-4 bg-gray-700 rounded w-1/4 mb-4" />
        <div className="h-48 bg-gray-700/30 rounded" />
      </div>
      {/* Table */}
      <SkeletonTable rows={5} cols={5} />
    </div>
  );
}
