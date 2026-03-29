"use client";
import { PortfolioSnapshot, Trade } from "../app/types";
import { useState, useMemo, useEffect } from "react";
import { useEscape } from "./useKeyboard";

interface PositionTableProps {
  positions: PortfolioSnapshot[];
}

const PositionTable: React.FC<PositionTableProps> = ({ positions }) => {
  const [filterText, setFilterText] = useState("");
  const [sortKey, setSortKey] = useState<keyof PortfolioSnapshot | null>(null);
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [showZero, setShowZero] = useState(false);

  // Stock detail modal
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [tickerTrades, setTickerTrades] = useState<Trade[]>([]);
  const [loadingTrades, setLoadingTrades] = useState(false);

  useEscape(selectedTicker ? () => setSelectedTicker(null) : null);

  const handleSort = (key: keyof PortfolioSnapshot) => {
    if (sortKey === key) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortOrder("desc");
    }
  };

  const negativePositions = useMemo(
    () => positions.filter((p) => p.quantity < -0.0001),
    [positions]
  );

  const sortedAndFilteredPositions = useMemo(() => {
    const q = filterText.toLowerCase();
    let data = positions.filter((p) => {
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

  const zeroCount = useMemo(
    () => positions.filter((p) => Math.abs(p.quantity) < 0.0001).length,
    [positions]
  );

  // Fetch trades for a ticker when modal opens
  const openStockDetail = (ticker: string) => {
    setSelectedTicker(ticker);
    setLoadingTrades(true);
    setTickerTrades([]);
    fetch("/api/trades")
      .then((r) => r.json())
      .then((allTrades: Trade[]) => {
        const filtered = allTrades
          .filter((t) => t.ticker === ticker)
          .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());
        setTickerTrades(filtered);
      })
      .catch(console.error)
      .finally(() => setLoadingTrades(false));
  };

  const selectedPosition = useMemo(
    () => positions.find((p) => p.ticker === selectedTicker),
    [positions, selectedTicker]
  );

  // Running totals for the trade history
  const tradesWithRunning = useMemo(() => {
    if (!tickerTrades.length) return [];
    // Sort chronologically for running calc
    const chronological = [...tickerTrades].sort(
      (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
    );
    let runningQty = 0;
    const mapped = chronological.map((t) => {
      if (t.side === "Buy") runningQty += t.quantity;
      else runningQty -= t.quantity;
      return { ...t, runningQty };
    });
    // Return in reverse chronological order (newest first)
    return mapped.reverse();
  }, [tickerTrades]);

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
    hideOnMobile,
  }: {
    colKey: keyof PortfolioSnapshot;
    label: string;
    right?: boolean;
    hideOnMobile?: boolean;
  }) => (
    <th
      className={`px-3 py-3 font-semibold cursor-pointer hover:text-white text-xs ${right ? "text-right" : ""} ${hideOnMobile ? "hidden md:table-cell" : ""}`}
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
              <TH colKey="primary_theme" label="Primary" hideOnMobile />
              <TH colKey="secondary_theme" label="Secondary" hideOnMobile />
              <TH colKey="quantity" label="Qty" right />
              <TH colKey="average_price" label="Avg Price" right hideOnMobile />
              <TH colKey="current_price" label="Current" right hideOnMobile />
              <TH colKey="market_value" label="Mkt Value" right />
              <TH colKey="unrealized_pnl" label="Unreal. P&L" right />
              <TH colKey="realized_pnl" label="Real. P&L" right hideOnMobile />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700">
            {sortedAndFilteredPositions.map((pos) => {
              const isNegative = pos.quantity < -0.0001;
              return (
                <tr
                  key={pos.ticker}
                  onClick={() => openStockDetail(pos.ticker)}
                  className={`hover:bg-gray-700/50 transition-colors cursor-pointer ${
                    isNegative ? "bg-red-900/10" : ""
                  }`}
                >
                  <td className="px-3 py-2.5 font-medium text-white">
                    {pos.ticker}
                    {isNegative && (
                      <span
                        className="ml-1.5 px-1.5 py-0.5 text-[10px] font-bold bg-red-600 text-red-100 rounded cursor-help"
                        title="Negative quantity — this may be a data entry error or a short position. Check your trade history."
                      >
                        SHORT?
                      </span>
                    )}
                  </td>
                  <td className="hidden md:table-cell px-3 py-2.5">
                    {pos.primary_theme ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); setFilterText(pos.primary_theme || ""); }}
                        className="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-900/40 text-indigo-300 border border-indigo-700/50 hover:bg-indigo-900/60 transition-colors"
                      >
                        {pos.primary_theme}
                      </button>
                    ) : (
                      <span className="text-gray-600 text-xs italic">--</span>
                    )}
                  </td>
                  <td className="hidden md:table-cell px-3 py-2.5">
                    {pos.secondary_theme ? (
                      <button
                        onClick={(e) => { e.stopPropagation(); setFilterText(pos.secondary_theme || ""); }}
                        className="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-900/40 text-cyan-300 border border-cyan-700/50 hover:bg-cyan-900/60 transition-colors">
                        {pos.secondary_theme}
                      </button>
                    ) : (
                      <span className="text-gray-600 text-xs italic">--</span>
                    )}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right ${isNegative ? "text-red-400 font-medium" : "text-gray-300"}`}
                  >
                    {pos.quantity.toLocaleString()}
                  </td>
                  <td className="hidden md:table-cell px-3 py-2.5 text-right text-gray-300">
                    ${pos.average_price.toFixed(2)}
                  </td>
                  <td className="hidden md:table-cell px-3 py-2.5 text-right text-gray-300">
                    ${pos.current_price.toFixed(2)}
                  </td>
                  <td className="px-3 py-2.5 text-right text-white font-medium">
                    ${pos.market_value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td
                    className={`px-3 py-2.5 text-right font-medium ${pos.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                  >
                    ${pos.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </td>
                  <td
                    className={`hidden md:table-cell px-3 py-2.5 text-right font-medium ${pos.realized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}
                  >
                    ${pos.realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
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
                  No positions yet. Import trades from <a href="/settings" className="text-indigo-400 hover:underline">Settings</a> or add one from the Dashboard.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Stock Detail Modal */}
      {selectedTicker && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50"
          onClick={(e) => { if (e.target === e.currentTarget) setSelectedTicker(null); }}
        >
          <div className="bg-gray-800 rounded-xl shadow-xl border border-gray-700 w-full max-w-5xl max-h-[85vh] flex flex-col">
            {/* Header */}
            <div className="p-6 pb-4 border-b border-gray-700">
              <div className="flex justify-between items-start">
                <div>
                  <h2 className="text-xl font-bold text-white">{selectedTicker}</h2>
                  {selectedPosition && (
                    <div className="flex gap-4 mt-2 text-sm">
                      {selectedPosition.primary_theme && (
                        <span className="px-2 py-0.5 rounded text-xs bg-indigo-900/40 text-indigo-300 border border-indigo-700/50">
                          {selectedPosition.primary_theme}
                        </span>
                      )}
                      {selectedPosition.secondary_theme && (
                        <span className="px-2 py-0.5 rounded text-xs bg-cyan-900/40 text-cyan-300 border border-cyan-700/50">
                          {selectedPosition.secondary_theme}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => setSelectedTicker(null)}
                  className="text-gray-400 hover:text-white text-xl px-2 hover:bg-gray-700 rounded"
                >
                  &times;
                </button>
              </div>

              {/* Position summary */}
              {selectedPosition && (
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-4">
                  <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700">
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Quantity</p>
                    <p className="text-sm font-bold text-white mt-0.5">{selectedPosition.quantity.toLocaleString()}</p>
                  </div>
                  <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700">
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Avg Price</p>
                    <p className="text-sm font-bold text-white mt-0.5">${selectedPosition.average_price.toFixed(2)}</p>
                  </div>
                  <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700">
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Current</p>
                    <p className="text-sm font-bold text-white mt-0.5">${selectedPosition.current_price.toFixed(2)}</p>
                  </div>
                  <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700">
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Unrealized</p>
                    <p className={`text-sm font-bold mt-0.5 ${selectedPosition.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${selectedPosition.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                  </div>
                  <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700">
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">Realized</p>
                    <p className={`text-sm font-bold mt-0.5 ${selectedPosition.realized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${selectedPosition.realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Trade history */}
            <div className="flex-1 overflow-auto p-6 pt-4">
              <h3 className="text-sm font-semibold text-gray-300 mb-3">
                Trade History ({tickerTrades.length} trades)
              </h3>

              {loadingTrades ? (
                <div className="flex justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
                </div>
              ) : tickerTrades.length === 0 ? (
                <p className="text-gray-500 text-sm italic py-4">No trades found.</p>
              ) : (
                <table className="min-w-full text-left text-sm whitespace-nowrap">
                  <thead className="text-gray-500 uppercase tracking-wider text-xs sticky top-0 bg-gray-800">
                    <tr>
                      <th className="px-3 py-2">Date</th>
                      <th className="px-3 py-2">Side</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">Price</th>
                      <th className="px-3 py-2 text-right">Total</th>
                      <th className="px-3 py-2 text-right" title="Position size after this trade">Position</th>
                      <th className="px-3 py-2 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700/50">
                    {tradesWithRunning.map((t, i) => (
                      <tr key={t.id || i} className="hover:bg-gray-700/30">
                        <td className="px-3 py-2 text-gray-300">
                          {new Date(t.date).toLocaleDateString()}
                        </td>
                        <td className={`px-3 py-2 font-semibold ${t.side === "Buy" ? "text-green-400" : "text-red-400"}`}>
                          {t.side}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-300">
                          {t.quantity.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-300">
                          ${t.price.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right text-white font-medium">
                          ${(t.quantity * t.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-400">
                          {t.runningQty.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-center">
                          {t.is_wash_sale && (
                            <span
                              className="px-1.5 py-0.5 text-[10px] font-bold bg-red-600 text-red-100 rounded cursor-help"
                              title="IRS Wash Sale: You sold at a loss and repurchased within 30 days. The loss is disallowed for tax purposes and added to the cost basis of the replacement shares."
                            >
                              WASH
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PositionTable;
