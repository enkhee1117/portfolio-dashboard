"use client";

import { useEffect, useState, useMemo } from "react";
import { PortfolioSnapshot } from "../types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

const COLORS = [
  "#6366f1", "#06b6d4", "#f59e0b", "#ef4444", "#8b5cf6",
  "#10b981", "#f97316", "#ec4899", "#14b8a6", "#a855f7",
  "#eab308", "#3b82f6", "#22c55e", "#e11d48", "#0ea5e9",
];

interface ThemeEntry {
  name: string;
  value: number;
  pnl: number;
  count: number;
}

export default function AnalyticsPage() {
  const [positions, setPositions] = useState<PortfolioSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedPrimary, setSelectedPrimary] = useState<string | null>(null);
  const [selectedSecondary, setSelectedSecondary] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/portfolio")
      .then((r) => r.json())
      .then((data) => setPositions(data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  // Long positions only
  const longPositions = useMemo(
    () => positions.filter((p) => p.quantity > 0 && p.market_value > 0),
    [positions]
  );

  const totalValue = useMemo(
    () => longPositions.reduce((s, p) => s + p.market_value, 0),
    [longPositions]
  );

  // Primary theme aggregation
  const primaryData: ThemeEntry[] = useMemo(() => {
    const map: Record<string, { value: number; pnl: number; count: number }> = {};
    longPositions.forEach((p) => {
      const t = p.primary_theme || "Unassigned";
      if (!map[t]) map[t] = { value: 0, pnl: 0, count: 0 };
      map[t].value += p.market_value;
      map[t].pnl += p.unrealized_pnl;
      map[t].count += 1;
    });
    return Object.entries(map)
      .map(([name, d]) => ({ name, ...d }))
      .sort((a, b) => b.value - a.value);
  }, [longPositions]);

  // Secondary theme aggregation
  const secondaryData: ThemeEntry[] = useMemo(() => {
    const map: Record<string, { value: number; pnl: number; count: number }> = {};
    longPositions.forEach((p) => {
      const t = p.secondary_theme || "Unassigned";
      if (!map[t]) map[t] = { value: 0, pnl: 0, count: 0 };
      map[t].value += p.market_value;
      map[t].pnl += p.unrealized_pnl;
      map[t].count += 1;
    });
    return Object.entries(map)
      .map(([name, d]) => ({ name, ...d }))
      .sort((a, b) => b.value - a.value);
  }, [longPositions]);

  // Stocks in selected theme
  const selectedStocks = useMemo(() => {
    if (selectedPrimary) {
      return longPositions
        .filter((p) => (p.primary_theme || "Unassigned") === selectedPrimary)
        .sort((a, b) => b.market_value - a.market_value);
    }
    if (selectedSecondary) {
      return longPositions
        .filter((p) => (p.secondary_theme || "Unassigned") === selectedSecondary)
        .sort((a, b) => b.market_value - a.market_value);
    }
    return [];
  }, [longPositions, selectedPrimary, selectedSecondary]);

  const selectedLabel = selectedPrimary || selectedSecondary;
  const selectedTotal = selectedStocks.reduce((s, p) => s + p.market_value, 0);

  // Concentration metrics
  const concentrationMetrics = useMemo(() => {
    if (primaryData.length === 0) return null;
    const top3 = primaryData.slice(0, 3);
    const top3Pct = totalValue > 0 ? (top3.reduce((s, d) => s + d.value, 0) / totalValue) * 100 : 0;
    // HHI (Herfindahl-Hirschman Index) — sum of squared market shares
    const hhi = primaryData.reduce((s, d) => {
      const share = totalValue > 0 ? (d.value / totalValue) * 100 : 0;
      return s + share * share;
    }, 0);
    return {
      themeCount: primaryData.length,
      top3Names: top3.map((d) => d.name),
      top3Pct,
      hhi: Math.round(hhi),
    };
  }, [primaryData, totalValue]);

  if (loading) {
    return (
      <main className="min-h-screen bg-gray-900 text-gray-100 p-8 flex justify-center items-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500" />
      </main>
    );
  }

  const renderBarChart = (
    data: ThemeEntry[],
    onBarClick: (name: string) => void,
    activeTheme: string | null
  ) => {
    const height = Math.max(280, data.length * 30);
    return (
      <div style={{ height, minWidth: 0 }} className="w-full overflow-hidden">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 0, right: 20, left: 0, bottom: 0 }}>
            <XAxis
              type="number"
              tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
              tick={{ fill: "#9ca3af", fontSize: 11 }}
              axisLine={{ stroke: "#374151" }}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={140}
              tick={{ fill: "#d1d5db", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              formatter={(value: any) => [
                `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 0 })} (${totalValue > 0 ? ((Number(value) / totalValue) * 100).toFixed(1) : 0}%)`,
                "Exposure",
              ]}
              contentStyle={{
                backgroundColor: "#1f2937",
                borderColor: "#374151",
                color: "#f3f4f6",
                borderRadius: "8px",
                fontSize: "13px",
              }}
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]} cursor="pointer" onClick={(d: any) => onBarClick(d.name as string)}>
              {data.map((entry, i) => (
                <Cell
                  key={entry.name}
                  fill={COLORS[i % COLORS.length]}
                  opacity={activeTheme && activeTheme !== entry.name ? 0.3 : 1}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  };

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Page Header */}
        <div>
          <h1 className="text-2xl font-bold text-white">Theme Analytics</h1>
          <p className="mt-1 text-sm text-gray-400">
            Portfolio exposure by investment theme &mdash; {longPositions.length} active positions
          </p>
        </div>

        {/* Concentration Metrics */}
        {concentrationMetrics && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
              <p className="text-xs text-gray-400 uppercase tracking-widest">Themes</p>
              <p className="mt-1 text-2xl font-bold text-white">{concentrationMetrics.themeCount}</p>
            </div>
            <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
              <p className="text-xs text-gray-400 uppercase tracking-widest">Top 3 Concentration</p>
              <p className="mt-1 text-2xl font-bold text-white">{concentrationMetrics.top3Pct.toFixed(1)}%</p>
            </div>
            <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
              <p className="text-xs text-gray-400 uppercase tracking-widest">HHI Index</p>
              <p className="mt-1 text-2xl font-bold text-white">{concentrationMetrics.hhi}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {concentrationMetrics.hhi < 1500 ? "Well diversified" : concentrationMetrics.hhi < 2500 ? "Moderate" : "Concentrated"}
              </p>
            </div>
            <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
              <p className="text-xs text-gray-400 uppercase tracking-widest">Top Themes</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {concentrationMetrics.top3Names.map((n) => (
                  <span key={n} className="px-1.5 py-0.5 text-xs rounded bg-indigo-900/40 text-indigo-300 border border-indigo-700/50">
                    {n}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Charts side by side on desktop */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Primary Themes */}
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
            <h3 className="text-lg font-semibold text-gray-200 mb-1">Primary Themes</h3>
            <p className="text-xs text-gray-400 mb-4">Click a bar to see positions</p>
            {renderBarChart(
              primaryData,
              (name) => {
                setSelectedSecondary(null);
                setSelectedPrimary(selectedPrimary === name ? null : name);
              },
              selectedPrimary
            )}
          </div>

          {/* Secondary Themes */}
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
            <h3 className="text-lg font-semibold text-gray-200 mb-1">Secondary Themes</h3>
            <p className="text-xs text-gray-400 mb-4">Click a bar to see positions</p>
            {renderBarChart(
              secondaryData,
              (name) => {
                setSelectedPrimary(null);
                setSelectedSecondary(selectedSecondary === name ? null : name);
              },
              selectedSecondary
            )}
          </div>
        </div>

        {/* Selected Theme Detail */}
        {selectedLabel && selectedStocks.length > 0 && (
          <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
            <div className="flex justify-between items-center mb-4">
              <div>
                <h3 className="text-lg font-semibold text-white">{selectedLabel}</h3>
                <p className="text-xs text-gray-400">
                  {selectedStocks.length} position{selectedStocks.length !== 1 ? "s" : ""} &middot; $
                  {selectedTotal.toLocaleString(undefined, { minimumFractionDigits: 0 })} total &middot;{" "}
                  {totalValue > 0 ? ((selectedTotal / totalValue) * 100).toFixed(1) : 0}% of portfolio
                </p>
              </div>
              <button
                onClick={() => { setSelectedPrimary(null); setSelectedSecondary(null); }}
                className="text-sm text-gray-400 hover:text-white px-3 py-1 rounded hover:bg-gray-700"
              >
                Close
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm whitespace-nowrap">
                <thead className="text-gray-500 uppercase tracking-wider text-xs">
                  <tr>
                    <th className="px-4 py-2">Ticker</th>
                    <th className="px-4 py-2">Primary</th>
                    <th className="px-4 py-2">Secondary</th>
                    <th className="px-4 py-2 text-right">Qty</th>
                    <th className="px-4 py-2 text-right">Mkt Value</th>
                    <th className="px-4 py-2 text-right">% of Theme</th>
                    <th className="px-4 py-2 text-right">Unreal. P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {selectedStocks.map((s) => (
                    <tr key={s.ticker} className="hover:bg-gray-700/30">
                      <td className="px-4 py-2.5 font-medium text-white">{s.ticker}</td>
                      <td className="px-4 py-2.5">
                        <span className="px-1.5 py-0.5 rounded text-xs bg-indigo-900/40 text-indigo-300">{s.primary_theme || "--"}</span>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="px-1.5 py-0.5 rounded text-xs bg-cyan-900/40 text-cyan-300">{s.secondary_theme || "--"}</span>
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-300">{s.quantity.toLocaleString()}</td>
                      <td className="px-4 py-2.5 text-right text-gray-300">
                        ${s.market_value.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-400">
                        {selectedTotal > 0 ? ((s.market_value / selectedTotal) * 100).toFixed(1) : 0}%
                      </td>
                      <td className={`px-4 py-2.5 text-right font-medium ${s.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                        ${s.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Theme Matrix */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <h3 className="text-lg font-semibold text-gray-200 mb-4">Theme Summary</h3>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm whitespace-nowrap">
              <thead className="text-gray-500 uppercase tracking-wider text-xs border-b border-gray-700">
                <tr>
                  <th className="px-4 py-3">Theme</th>
                  <th className="px-4 py-3 text-right">Stocks</th>
                  <th className="px-4 py-3 text-right">Exposure</th>
                  <th className="px-4 py-3 text-right">% Portfolio</th>
                  <th className="px-4 py-3 text-right">Unrealized P&L</th>
                  <th className="px-4 py-3 text-right">Avg P&L / Stock</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {primaryData.map((d) => (
                  <tr key={d.name} className="hover:bg-gray-700/30">
                    <td className="px-4 py-2.5 font-medium text-white">{d.name}</td>
                    <td className="px-4 py-2.5 text-right text-gray-300">{d.count}</td>
                    <td className="px-4 py-2.5 text-right text-gray-300">
                      ${d.value.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-400">
                      {totalValue > 0 ? ((d.value / totalValue) * 100).toFixed(1) : 0}%
                    </td>
                    <td className={`px-4 py-2.5 text-right font-medium ${d.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${d.pnl.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                    </td>
                    <td className={`px-4 py-2.5 text-right ${d.count > 0 ? (d.pnl / d.count >= 0 ? "text-green-400" : "text-red-400") : "text-gray-500"}`}>
                      ${d.count > 0 ? (d.pnl / d.count).toLocaleString(undefined, { minimumFractionDigits: 0 }) : "0"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </main>
  );
}
