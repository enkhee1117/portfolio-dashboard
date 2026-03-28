"use client";
import { PortfolioSnapshot } from "../app/types";
import { useState, useMemo } from "react";

interface PositionTableProps {
  positions: PortfolioSnapshot[];
}

const PositionTable: React.FC<PositionTableProps> = ({ positions }) => {
  const [filterText, setFilterText] = useState("");
  const [sortKey, setSortKey] = useState<keyof PortfolioSnapshot | null>(null);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [showZero, setShowZero] = useState(false);

  const handleSort = (key: keyof PortfolioSnapshot) => {
    if (sortKey === key) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortOrder("desc");
    }
  };

  // Separate negative-quantity positions for flagging
  const negativePositions = useMemo(
    () => positions.filter((p) => p.quantity < -0.0001),
    [positions]
  );

  const sortedAndFilteredPositions = useMemo(() => {
    const q = filterText.toLowerCase();
    let data = positions.filter((p) => {
      // Hide zero-exposure unless toggled on
      if (!showZero && Math.abs(p.quantity) < 0.0001) return false;
      return (
        p.ticker.toLowerCase().includes(q) ||
        (p.primary_theme || "").toLowerCase().includes(q) ||
        (p.secondary_theme || "").toLowerCase().includes(q)
      );
    });

    if (sortKey) {
      data.sort((a, b) => {
        const valA = (a[sortKey] as string | number) ?? "";
        const valB = (b[sortKey] as string | number) ?? "";
        if (valA < valB) return sortOrder === "asc" ? -1 : 1;
        if (valA > valB) return sortOrder === "asc" ? 1 : -1;
        return 0;
      });
    }
    return data;
  }, [positions, filterText, sortKey, sortOrder, showZero]);

  const zeroCount = useMemo(() => positions.filter((p) => Math.abs(p.quantity) < 0.0001).length, [positions]);

  const SortIcon = ({ colKey }: { colKey: keyof PortfolioSnapshot }) => {
    if (sortKey !== colKey)
      return <span className="text-gray-600 ml-1">&#8693;</span>;
    return (
      <span className="ml-1 text-white">
        {sortOrder === "asc" ? "\u2191" : "\u2193"}
      </span>
    );
  };

  const TH = ({
    colKey,
    label,
    right,
  }: {
    colKey: keyof PortfolioSnapshot;
    label: string;
    right?: boolean;
  }) => (
    <th
      className={`px-3 py-3 font-semibold cursor-pointer hover:text-white text-xs ${right ? "text-right" : ""}`}
      onClick={() => handleSort(colKey)}
    >
      {label} <SortIcon colKey={colKey} />
    </th>
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Negative quantity warning */}
      {negativePositions.length > 0 && (
        <div className="p-3 bg-red-900/20 border border-red-700/50 rounded-lg">
          <p className="text-sm text-red-300 font-medium">
            {negativePositions.length} ticker
            {negativePositions.length !== 1 ? "s" : ""} with negative exposure
            (possible entry error or short position):
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {negativePositions.map((p) => (
              <span
                key={p.ticker}
                className="px-2 py-1 text-xs font-medium bg-red-900/40 text-red-300 border border-red-700/50 rounded"
              >
                {p.ticker}{" "}
                <span className="text-red-400">
                  {p.quantity.toLocaleString()} shares
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Filter & controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Filter by ticker or theme..."
          value={filterText}
          onChange={(e) => setFilterText(e.target.value)}
          className="bg-gray-700 text-white px-4 py-2 rounded-lg border border-gray-600 focus:outline-none focus:border-indigo-500 w-full md:w-80 text-sm"
        />
        {zeroCount > 0 && (
          <button
            onClick={() => setShowZero(!showZero)}
            className={`px-3 py-2 rounded-lg border text-xs transition-colors ${
              showZero
                ? "border-gray-500 bg-gray-700 text-gray-300"
                : "border-gray-700 bg-gray-800 text-gray-500 hover:text-gray-300"
            }`}
          >
            {showZero ? `Hide ${zeroCount} closed` : `Show ${zeroCount} closed`}
          </button>
        )}
      </div>

      <div className="overflow-x-auto rounded-xl border border-gray-700 bg-gray-800 shadow-xl">
        <table className="w-full text-left text-sm whitespace-nowrap">
          <thead className="bg-gray-900/50 uppercase tracking-wider border-b border-gray-700 text-gray-400">
            <tr>
              <TH colKey="ticker" label="Ticker" />
              <TH colKey="primary_theme" label="Primary" />
              <TH colKey="secondary_theme" label="Secondary" />
              <TH colKey="quantity" label="Qty" right />
              <TH colKey="average_price" label="Avg Price" right />
              <TH colKey="current_price" label="Current" right />
              <TH colKey="market_value" label="Mkt Value" right />
              <TH colKey="unrealized_pnl" label="Unreal. P&L" right />
              <TH colKey="realized_pnl" label="Real. P&L" right />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {sortedAndFilteredPositions.map((pos) => {
              const isNegative = pos.quantity < 0;
              return (
                <tr
                  key={pos.ticker}
                  className={`hover:bg-gray-700/50 transition-colors ${
                    isNegative ? "bg-red-900/10" : ""
                  }`}
                >
                  <td className="px-3 py-2.5 font-medium text-white">
                    {pos.ticker}
                    {isNegative && (
                      <span className="ml-1.5 px-1.5 py-0.5 text-[10px] font-bold bg-red-600 text-red-100 rounded">
                        SHORT?
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {pos.primary_theme ? (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-900/40 text-indigo-300 border border-indigo-700/50">
                        {pos.primary_theme}
                      </span>
                    ) : (
                      <span className="text-gray-600 text-xs italic">--</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {pos.secondary_theme ? (
                      <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-900/40 text-cyan-300 border border-cyan-700/50">
                        {pos.secondary_theme}
                      </span>
                    ) : (
                      <span className="text-gray-600 text-xs italic">--</span>
                    )}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right ${isNegative ? "text-red-400 font-medium" : "text-gray-300"}`}
                  >
                    {pos.quantity.toLocaleString()}
                  </td>
                  <td className="px-3 py-2.5 text-right text-gray-300">
                    ${pos.average_price.toFixed(2)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-gray-300">
                    ${pos.current_price.toFixed(2)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-white font-medium">
                    ${pos.market_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right font-medium ${pos.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                  >
                    ${pos.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right font-medium ${pos.realized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                  >
                    ${pos.realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </td>
                </tr>
              );
            })}
            {sortedAndFilteredPositions.length === 0 && (
              <tr>
                <td
                  colSpan={9}
                  className="px-6 py-8 text-center text-gray-500 italic"
                >
                  No positions found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default PositionTable;
