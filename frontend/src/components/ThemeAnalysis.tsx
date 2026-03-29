"use client";
import { useMemo, useState } from "react";
import { PortfolioSnapshot } from "../app/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface ThemeAnalysisProps {
  positions: PortfolioSnapshot[];
}

interface ThemeEntry {
  name: string;
  value: number;
}

const COLORS = [
  "#6366f1", "#06b6d4", "#f59e0b", "#ef4444", "#8b5cf6",
  "#10b981", "#f97316", "#ec4899", "#14b8a6", "#a855f7",
  "#eab308", "#3b82f6", "#22c55e", "#e11d48", "#0ea5e9",
];

const ThemeAnalysis: React.FC<ThemeAnalysisProps> = ({ positions }) => {
  const [selectedTheme, setSelectedTheme] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<"primary" | "secondary" | null>(null);

  const longPositions = useMemo(
    () => positions.filter((p) => p.quantity > 0 && p.market_value > 0),
    [positions]
  );

  const totalValue = useMemo(
    () => longPositions.reduce((s, p) => s + p.market_value, 0),
    [longPositions]
  );

  const primaryData: ThemeEntry[] = useMemo(() => {
    const map: Record<string, number> = {};
    longPositions.forEach((p) => {
      const t = p.primary_theme || "Unassigned";
      map[t] = (map[t] || 0) + p.market_value;
    });
    return Object.entries(map)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [longPositions]);

  const secondaryData: ThemeEntry[] = useMemo(() => {
    const map: Record<string, number> = {};
    longPositions.forEach((p) => {
      const t = p.secondary_theme || "Unassigned";
      map[t] = (map[t] || 0) + p.market_value;
    });
    return Object.entries(map)
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [longPositions]);

  const selectedStocks = useMemo(() => {
    if (!selectedTheme || !selectedType) return [];
    return longPositions
      .filter((p) => {
        const theme =
          selectedType === "primary"
            ? p.primary_theme || "Unassigned"
            : p.secondary_theme || "Unassigned";
        return theme === selectedTheme;
      })
      .sort((a, b) => b.market_value - a.market_value);
  }, [longPositions, selectedTheme, selectedType]);

  const selectedTotal = selectedStocks.reduce((s, p) => s + p.market_value, 0);

  if (primaryData.length === 0) return null;

  const handleBarClick = (type: "primary" | "secondary", name: string) => {
    if (selectedType === type && selectedTheme === name) {
      setSelectedTheme(null);
      setSelectedType(null);
    } else {
      setSelectedTheme(name);
      setSelectedType(type);
    }
  };

  const closeModal = () => {
    setSelectedTheme(null);
    setSelectedType(null);
  };

  const renderChart = (
    data: ThemeEntry[],
    type: "primary" | "secondary",
    label: string
  ) => {
    const chartHeight = Math.max(280, data.length * 30);
    const isActive = selectedType === type;

    return (
      <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
        <h3 className="text-lg font-semibold text-gray-200 mb-1">{label}</h3>
        <p className="text-xs text-gray-400 mb-4">
          Click any bar to see individual positions
        </p>
        <div
          style={{ height: chartHeight, minWidth: 0 }}
          className="w-full overflow-hidden"
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data}
              layout="vertical"
              margin={{ top: 0, right: 20, left: 0, bottom: 0 }}
            >
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
                tick={{ fill: "#d1d5db", fontSize: 12 }}
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
              <Bar
                dataKey="value"
                radius={[0, 4, 4, 0]}
                cursor="pointer"
                onClick={(d: any) => handleBarClick(type, d.name as string)}
              >
                {data.map((entry, index) => (
                  <Cell
                    key={entry.name}
                    fill={COLORS[index % COLORS.length]}
                    opacity={
                      isActive && selectedTheme !== entry.name ? 0.3 : 1
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Two charts side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {renderChart(primaryData, "primary", "Primary Theme Exposure")}
        {renderChart(secondaryData, "secondary", "Secondary Theme Exposure")}
      </div>

      {/* Theme detail MODAL */}
      {selectedTheme && selectedStocks.length > 0 && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50"
          onClick={(e) => { if (e.target === e.currentTarget) closeModal(); }}
        >
          <div className="bg-gray-800 rounded-xl shadow-xl border border-gray-700 w-full max-w-3xl max-h-[80vh] flex flex-col">
            {/* Header */}
            <div className="flex justify-between items-center p-6 pb-4 border-b border-gray-700">
              <div>
                <h3 className="text-lg font-semibold text-white">
                  {selectedTheme}
                  <span className="ml-2 text-xs font-normal px-2 py-0.5 rounded bg-gray-700 text-gray-400">
                    {selectedType === "primary" ? "Primary" : "Secondary"}
                  </span>
                </h3>
                <p className="text-xs text-gray-400 mt-1">
                  {selectedStocks.length} position
                  {selectedStocks.length !== 1 ? "s" : ""} &middot; $
                  {selectedTotal.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                  {" "}total &middot;{" "}
                  {totalValue > 0 ? ((selectedTotal / totalValue) * 100).toFixed(1) : 0}% of portfolio
                </p>
              </div>
              <button
                onClick={closeModal}
                className="text-gray-400 hover:text-white text-xl px-2 hover:bg-gray-700 rounded"
              >
                &times;
              </button>
            </div>

            {/* Scrollable table */}
            <div className="overflow-auto flex-1 p-6 pt-0">
              <table className="min-w-full text-left text-sm whitespace-nowrap">
                <thead className="text-gray-500 uppercase tracking-wider text-xs sticky top-0 bg-gray-800">
                  <tr>
                    <th className="px-4 py-3">Ticker</th>
                    <th className="px-4 py-3">Primary</th>
                    <th className="px-4 py-3">Secondary</th>
                    <th className="px-4 py-3 text-right">Qty</th>
                    <th className="px-4 py-3 text-right">Mkt Value</th>
                    <th className="px-4 py-3 text-right">% of Theme</th>
                    <th className="px-4 py-3 text-right">% Portfolio</th>
                    <th className="px-4 py-3 text-right">Unreal. P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {selectedStocks.map((s) => (
                    <tr key={s.ticker} className="hover:bg-gray-700/30">
                      <td className="px-4 py-2.5 font-medium text-white">{s.ticker}</td>
                      <td className="px-4 py-2.5">
                        <span className="px-1.5 py-0.5 rounded text-xs bg-indigo-900/40 text-indigo-300 border border-indigo-700/50">
                          {s.primary_theme || "--"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="px-1.5 py-0.5 rounded text-xs bg-cyan-900/40 text-cyan-300 border border-cyan-700/50">
                          {s.secondary_theme || "--"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-300">{s.quantity.toLocaleString()}</td>
                      <td className="px-4 py-2.5 text-right text-gray-300">
                        ${s.market_value.toLocaleString(undefined, { minimumFractionDigits: 0 })}
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-400">
                        {selectedTotal > 0 ? ((s.market_value / selectedTotal) * 100).toFixed(1) : 0}%
                      </td>
                      <td className="px-4 py-2.5 text-right text-gray-400">
                        {totalValue > 0 ? ((s.market_value / totalValue) * 100).toFixed(1) : 0}%
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
        </div>
      )}
    </div>
  );
};

export default ThemeAnalysis;
