"use client";
import { useState, useEffect } from "react";
import { PortfolioHistoryPoint } from "../app/types";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const PERIODS = [
  { key: "ytd", label: "YTD" },
  { key: "1m", label: "1M" },
  { key: "3m", label: "3M" },
  { key: "6m", label: "6M" },
  { key: "1y", label: "1Y" },
  { key: "all", label: "ALL" },
];

export default function PortfolioChart() {
  const [period, setPeriod] = useState("ytd");
  const [data, setData] = useState<PortfolioHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/portfolio/history?period=${period}`)
      .then((r) => r.json())
      .then((d) => setData(d))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [period]);

  // Compute change from first to last point
  const firstValue = data.length > 0 ? data[0].value : 0;
  const lastValue = data.length > 0 ? data[data.length - 1].value : 0;
  const change = lastValue - firstValue;
  const changePct = firstValue > 0 ? (change / firstValue) * 100 : 0;
  const isPositive = change >= 0;

  // Gradient color based on gain/loss
  const gradientColor = isPositive ? "#10b981" : "#ef4444";
  const lineColor = isPositive ? "#10b981" : "#ef4444";

  if (data.length === 0 && !loading) {
    return (
      <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
        <h3 className="text-lg font-semibold text-gray-200">Portfolio Value</h3>
        <p className="text-sm text-gray-400 mt-2">
          No historical data available. Run{" "}
          <a href="/settings" className="text-indigo-400 hover:underline">
            Backfill Historical Prices
          </a>{" "}
          from Settings to populate price history.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start gap-3 mb-4">
        <div>
          <h3 className="text-lg font-semibold text-gray-200">Portfolio Value</h3>
          {data.length > 0 && (
            <div className="flex items-baseline gap-3 mt-1">
              <span className="text-2xl font-bold text-white">
                ${lastValue.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
              </span>
              <span className={`text-sm font-medium ${isPositive ? "text-green-400" : "text-red-400"}`}>
                {isPositive ? "+" : ""}${change.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                {" "}({isPositive ? "+" : ""}{changePct.toFixed(1)}%)
              </span>
            </div>
          )}
        </div>

        {/* Period selector */}
        <div className="flex gap-0.5 bg-gray-900/50 rounded-lg p-0.5 flex-shrink-0">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                period === p.key
                  ? "bg-gray-700 text-white"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
        </div>
      ) : (
        <div style={{ height: 280, minWidth: 0 }} className="w-full overflow-hidden">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="portfolioGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={gradientColor} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={gradientColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="date"
                tickFormatter={(d) => {
                  const dt = new Date(d);
                  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
                }}
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={{ stroke: "#374151" }}
                tickLine={false}
                minTickGap={50}
              />
              <YAxis
                tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                tick={{ fill: "#9ca3af", fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                width={60}
                domain={['auto', 'auto']}
              />
              <Tooltip
                formatter={(value: any) => [
                  `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                  "Portfolio Value",
                ]}
                labelFormatter={(label) => {
                  const dt = new Date(label);
                  return dt.toLocaleDateString(undefined, {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  });
                }}
                contentStyle={{
                  backgroundColor: "#1f2937",
                  borderColor: "#374151",
                  color: "#f3f4f6",
                  borderRadius: "8px",
                  fontSize: "13px",
                }}
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={lineColor}
                strokeWidth={2}
                fill="url(#portfolioGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
