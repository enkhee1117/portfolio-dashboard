"use client";

import { useEffect, useState, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import PositionTable from "../../components/PositionTable";
import { Trade } from "../types";
import { useToast } from "../../components/Toast";
import { apiCall } from "../../lib/api";
import { useAuth } from "../../lib/AuthContext";
import { usePortfolio } from "../../lib/PortfolioContext";
import { useEscape, useCmdK } from "../../components/useKeyboard";
import { SkeletonTable } from "../../components/Skeleton";

type TabType = "positions" | "trades" | "assets";

function PortfolioContent() {
  const { user } = useAuth();
  const { positions, assets, loading: posLoading, themes, refresh } = usePortfolio();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const tickerParam = searchParams.get("ticker");
  const initialTab: TabType = tabParam === "trades" ? "trades" : tabParam === "assets" ? "assets" : "positions";
  const [tab, setTab] = useState<TabType>(initialTab);

  // Trades (lazy-loaded, page-specific)
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradeLoading, setTradeLoading] = useState(true);

  // Asset filters (local UI state)
  const assetLoading = posLoading;
  const [assetFilter, setAssetFilter] = useState("");
  const [primaryFilter, setPrimaryFilter] = useState("");
  const [secondaryFilter, setSecondaryFilter] = useState("");
  const [assetPage, setAssetPage] = useState(0);
  const ASSETS_PER_PAGE = 50;

  const toast = useToast();
  useCmdK();

  const [filterText, setFilterText] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortKey, setSortKey] = useState<keyof Trade | null>("date");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [editingTrade, setEditingTrade] = useState<Trade | null>(null);

  // Asset detail modal (trade history for any ticker)
  const [detailTicker, setDetailTicker] = useState<string | null>(null);
  const [detailTrades, setDetailTrades] = useState<Trade[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);

  const openTickerDetail = (ticker: string) => {
    setDetailTicker(ticker);
    setDetailLoading(true);
    setDetailTrades([]);
    apiCall(`/api/trades?ticker=${encodeURIComponent(ticker)}&limit=0`)
      .then(async (r) => {
        if (r.ok) {
          const data = await r.json();
          setDetailTrades(data);
        } else {
          console.error(`Failed to fetch trades for ${ticker}: ${r.status}`);
        }
      })
      .catch((err) => console.error(`Error fetching trades for ${ticker}:`, err))
      .finally(() => setDetailLoading(false));
  };

  // Auto-open ticker detail if linked from dashboard
  useEffect(() => {
    if (tickerParam && user) {
      openTickerDetail(tickerParam.toUpperCase());
    }
  }, [tickerParam, user]);

  useEscape(detailTicker ? () => setDetailTicker(null) : editingTrade ? () => setEditingTrade(null) : null);

  // Positions + assets come from PortfolioContext (shared, fetched once)

  // Lazy-load trades only when Trades tab is active (expensive — streams all trades)
  useEffect(() => {
    if (!user || tab !== "trades") return;
    if (trades.length > 0) return; // Already loaded
    setTradeLoading(true);
    apiCall("/api/trades?limit=0")
      .then(async (r) => { if (r.ok) setTrades(await r.json()); })
      .catch(console.error)
      .finally(() => setTradeLoading(false));
  }, [user, tab]);

  const activeCount = positions.filter((p) => p.quantity > 0).length;

  // Trade sorting/filtering
  const handleSort = (key: keyof Trade) => {
    if (sortKey === key) setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortOrder("desc"); }
  };

  const filteredTrades = useMemo(() => {
    const q = filterText.toLowerCase();
    let data = trades.filter((t) => {
      const matchesText = !q || t.ticker.toLowerCase().includes(q) || t.type.toLowerCase().includes(q);
      const tradeDate = t.date.slice(0, 10);
      return matchesText && (!dateFrom || tradeDate >= dateFrom) && (!dateTo || tradeDate <= dateTo);
    });
    if (sortKey) {
      data.sort((a, b) => {
        const vA = a[sortKey] ?? ""; const vB = b[sortKey] ?? "";
        if (vA < vB) return sortOrder === "asc" ? -1 : 1;
        if (vA > vB) return sortOrder === "asc" ? 1 : -1;
        return 0;
      });
    }
    return data;
  }, [trades, filterText, dateFrom, dateTo, sortKey, sortOrder]);

  const SortIcon = ({ colKey }: { colKey: keyof Trade }) => {
    if (sortKey !== colKey) return <span className="text-gray-600 ml-1">&#8693;</span>;
    return <span className="ml-1 text-white">{sortOrder === "asc" ? "\u2191" : "\u2193"}</span>;
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this trade?")) return;
    try {
      const res = await apiCall(`/api/trades/${id}`, { method: "DELETE" });
      if (res.ok) {
        setTrades(trades.filter((t) => t.id !== id));
        toast.success("Trade deleted");
      } else {
        toast.error("Failed to delete trade");
      }
    } catch { toast.error("Error deleting trade"); }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingTrade) return;
    try {
      const res = await apiCall(`/api/trades/${editingTrade.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...editingTrade, price: Number(editingTrade.price), quantity: Number(editingTrade.quantity) }),
      });
      if (res.ok) {
        const updated = await res.json();
        setTrades(trades.map((t) => (t.id === updated.id ? updated : t)));
        setEditingTrade(null);
      } else toast.error("Failed to update trade");
    } catch { toast.error("Error updating trade"); }
  };

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header + Tabs */}
        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
          <div>
            <h1 className="text-2xl font-bold text-white">Portfolio</h1>
            <p className="mt-1 text-sm text-gray-400">
              {tab === "positions" ? `${activeCount} active positions` : tab === "trades" ? `${trades.length} total trades` : `${assets.length} registered assets`}
            </p>
          </div>
          <div className="flex gap-0.5 bg-gray-800 rounded-lg p-0.5 border border-gray-700">
            {([
              { key: "positions" as TabType, label: "Positions" },
              { key: "trades" as TabType, label: "Trades" },
              { key: "assets" as TabType, label: "Assets" },
            ]).map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  tab === t.key ? "bg-gray-700 text-white" : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {/* Positions Tab */}
        {tab === "positions" && (
          posLoading ? (
            <SkeletonTable rows={8} cols={5} />
          ) : (
            <>
              {/* Top Gainers & Losers */}
              {positions.filter(p => p.quantity > 0).length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="bg-gray-800 rounded-xl p-5 shadow-lg border border-gray-700">
                    <h3 className="text-sm font-semibold text-green-400 uppercase tracking-widest mb-3">Top Gainers</h3>
                    <div className="space-y-1.5">
                      {positions
                        .filter(p => p.quantity > 0 && p.unrealized_pnl > 0)
                        .sort((a, b) => b.unrealized_pnl - a.unrealized_pnl)
                        .slice(0, 10)
                        .map(pos => {
                          const pct = pos.average_price > 0 ? ((pos.current_price - pos.average_price) / pos.average_price) * 100 : 0;
                          return (
                            <div key={pos.ticker} onClick={() => openTickerDetail(pos.ticker)} className="flex items-center justify-between py-0.5 cursor-pointer hover:bg-gray-700/30 rounded px-1 -mx-1">
                              <div className="flex items-center gap-2">
                                <span className="text-white font-medium text-sm w-14">{pos.ticker}</span>
                                <span className="text-xs text-gray-500">${pos.current_price.toFixed(2)}</span>
                              </div>
                              <div className="text-right">
                                <span className="text-green-400 text-sm font-medium">+${pos.unrealized_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                                <span className="text-green-400/70 text-xs ml-2 w-16 inline-block text-right">+{pct.toFixed(1)}%</span>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  </div>
                  <div className="bg-gray-800 rounded-xl p-5 shadow-lg border border-gray-700">
                    <h3 className="text-sm font-semibold text-red-400 uppercase tracking-widest mb-3">Top Losers</h3>
                    <div className="space-y-1.5">
                      {positions
                        .filter(p => p.quantity > 0 && p.unrealized_pnl < 0)
                        .sort((a, b) => a.unrealized_pnl - b.unrealized_pnl)
                        .slice(0, 10)
                        .map(pos => {
                          const pct = pos.average_price > 0 ? ((pos.current_price - pos.average_price) / pos.average_price) * 100 : 0;
                          return (
                            <div key={pos.ticker} onClick={() => openTickerDetail(pos.ticker)} className="flex items-center justify-between py-0.5 cursor-pointer hover:bg-gray-700/30 rounded px-1 -mx-1">
                              <div className="flex items-center gap-2">
                                <span className="text-white font-medium text-sm w-14">{pos.ticker}</span>
                                <span className="text-xs text-gray-500">${pos.current_price.toFixed(2)}</span>
                              </div>
                              <div className="text-right">
                                <span className="text-red-400 text-sm font-medium">${pos.unrealized_pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                                <span className="text-red-400/70 text-xs ml-2 w-16 inline-block text-right">{pct.toFixed(1)}%</span>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  </div>
                </div>
              )}
              <PositionTable positions={positions} />
            </>
          )
        )}

        {/* Trades Tab */}
        {tab === "trades" && (
          <>
            {/* Filters */}
            <div className="flex items-center gap-3 flex-wrap">
              <input
                type="text"
                placeholder="Filter by Ticker or Type..."
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                className="bg-gray-800 text-white px-4 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 w-full md:w-64 text-sm"
              />
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <span>From</span>
                <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                  className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 text-sm [&::-webkit-calendar-picker-indicator]:invert" />
                <span>To</span>
                <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                  className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 text-sm [&::-webkit-calendar-picker-indicator]:invert" />
                {(dateFrom || dateTo) && (
                  <button onClick={() => { setDateFrom(""); setDateTo(""); }} className="text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700">Clear dates</button>
                )}
              </div>
              <span className="text-xs text-gray-500 ml-auto">{filteredTrades.length} of {trades.length} trades</span>
            </div>

            {/* Trade Table */}
            {tradeLoading ? (
              <SkeletonTable rows={10} cols={6} />
            ) : (
              <div className="overflow-x-auto rounded-xl border border-gray-700 bg-gray-800 shadow-xl">
                <table className="min-w-full text-left text-sm whitespace-nowrap">
                  <thead className="bg-gray-900/50 uppercase tracking-wider border-b border-gray-700 text-gray-400">
                    <tr>
                      <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort("date")}>Date <SortIcon colKey="date" /></th>
                      <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort("ticker")}>Ticker <SortIcon colKey="ticker" /></th>
                      <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort("side")}>Side <SortIcon colKey="side" /></th>
                      <th className="px-6 py-4 text-right cursor-pointer hover:text-white" onClick={() => handleSort("quantity")}>Qty <SortIcon colKey="quantity" /></th>
                      <th className="px-6 py-4 text-right cursor-pointer hover:text-white" onClick={() => handleSort("price")}>Price <SortIcon colKey="price" /></th>
                      <th className="px-6 py-4 text-right hidden sm:table-cell">Total</th>
                      <th className="px-6 py-4 text-center hidden sm:table-cell">Status</th>
                      <th className="px-6 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700">
                    {filteredTrades.map((trade) => (
                      <tr key={trade.id} className={`hover:bg-gray-700/50 transition-colors ${trade.is_wash_sale ? "bg-red-900/10" : ""}`}>
                        <td className="px-6 py-4 text-gray-300">{new Date(trade.date).toLocaleDateString()}</td>
                        <td className="px-6 py-4 font-medium text-white">{trade.ticker}</td>
                        <td className={`px-6 py-4 font-semibold ${trade.side === "Buy" ? "text-green-400" : "text-red-400"}`}>{trade.side}</td>
                        <td className="px-6 py-4 text-right text-gray-300">{trade.quantity.toLocaleString()}</td>
                        <td className="px-6 py-4 text-right text-gray-300">${trade.price.toFixed(2)}</td>
                        <td className="px-6 py-4 text-right text-white font-medium hidden sm:table-cell">
                          ${(trade.quantity * trade.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                        <td className="px-6 py-4 text-center hidden sm:table-cell">
                          {trade.is_wash_sale && (
                            <span className="px-2 py-1 text-xs font-bold text-red-100 bg-red-600 rounded-full cursor-help"
                              title="IRS Wash Sale: You sold at a loss and repurchased within 30 days. The loss is disallowed for tax purposes and added to the cost basis of the replacement shares.">
                              WASH SALE
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-right space-x-2">
                          <button onClick={() => setEditingTrade(trade)} className="text-blue-400 hover:text-blue-300 text-xs">Edit</button>
                          <button onClick={() => handleDelete(trade.id)} className="text-red-400 hover:text-red-300 text-xs">Delete</button>
                        </td>
                      </tr>
                    ))}
                    {filteredTrades.length === 0 && !tradeLoading && (
                      <tr>
                        <td colSpan={8} className="px-6 py-8 text-center text-gray-500 italic">
                          No trades found. Import your trade history from <a href="/settings" className="text-indigo-400 hover:underline">Settings</a> or add trades from the <a href="/" className="text-indigo-400 hover:underline">Dashboard</a>.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {/* Assets Tab */}
        {tab === "assets" && (
          assetLoading ? (
            <SkeletonTable rows={8} cols={5} />
          ) : (
            <>
              <div className="flex items-center gap-3 flex-wrap">
                <input type="text" placeholder="Search ticker or theme..." value={assetFilter} onChange={(e) => { setAssetFilter(e.target.value); setAssetPage(0); }}
                  className="bg-gray-800 text-white px-4 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 w-full md:w-64 text-sm" />
                <select value={primaryFilter} onChange={(e) => { setPrimaryFilter(e.target.value); setAssetPage(0); }} className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 text-sm">
                  <option value="">All Primary</option>
                  {themes.primary.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <select value={secondaryFilter} onChange={(e) => { setSecondaryFilter(e.target.value); setAssetPage(0); }} className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 text-sm">
                  <option value="">All Secondary</option>
                  {themes.secondary.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                {(assetFilter || primaryFilter || secondaryFilter) && (
                  <button onClick={() => { setAssetFilter(""); setPrimaryFilter(""); setSecondaryFilter(""); setAssetPage(0); }} className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700">Clear</button>
                )}
                <span className="text-xs text-gray-500 ml-auto">
                  {(() => {
                    const q = assetFilter.toLowerCase();
                    const filtered = assets.filter(a =>
                      (!q || a.ticker.toLowerCase().includes(q) || a.primary_theme.toLowerCase().includes(q) || a.secondary_theme.toLowerCase().includes(q))
                      && (!primaryFilter || a.primary_theme === primaryFilter)
                      && (!secondaryFilter || a.secondary_theme === secondaryFilter)
                    );
                    const totalPages = Math.ceil(filtered.length / ASSETS_PER_PAGE);
                    return `${Math.min(assetPage * ASSETS_PER_PAGE + 1, filtered.length)}-${Math.min((assetPage + 1) * ASSETS_PER_PAGE, filtered.length)} of ${filtered.length}`;
                  })()}
                </span>
              </div>
              {/* Failed price banner */}
              {assets.filter(a => a.price === 0).length > 0 && (
                <div className="bg-amber-900/20 border border-amber-700/50 rounded-xl p-4">
                  <div className="flex items-start gap-2">
                    <span className="text-amber-300 text-sm font-medium">Price data unavailable for {assets.filter(a => a.price === 0).length} ticker{assets.filter(a => a.price === 0).length > 1 ? "s" : ""} (delisted or invalid):</span>
                  </div>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {assets.filter(a => a.price === 0).map(a => (
                      <span key={a.ticker} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-800 border border-gray-700 text-sm">
                        <span className="text-white font-medium">{a.ticker}</span>
                        <button
                          onClick={async () => {
                            if (!confirm(`Remove "${a.ticker}" from assets?\n\nTrade history will be preserved.`)) return;
                            try {
                              const res = await apiCall(`/api/assets/${a.ticker}`, { method: "DELETE" });
                              if (res.ok) {
                                refresh();
                                toast.success(`${a.ticker} removed`);
                              } else toast.error("Failed to remove");
                            } catch { toast.error("Error removing asset"); }
                          }}
                          className="ml-0.5 text-red-400 hover:text-red-300 font-medium transition-colors"
                          title="Remove from assets"
                        >&times;</button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="overflow-x-auto rounded-xl border border-gray-700 bg-gray-800 shadow-xl">
                <table className="min-w-full text-left text-sm whitespace-nowrap">
                  <thead className="bg-gray-900/50 uppercase tracking-wider border-b border-gray-700 text-gray-400">
                    <tr>
                      <th className="px-4 py-3 text-xs">Ticker</th>
                      <th className="px-4 py-3 text-xs">Primary</th>
                      <th className="px-4 py-3 text-xs">Secondary</th>
                      <th className="px-4 py-3 text-xs text-right">Price</th>
                      <th className="px-4 py-3 text-xs text-right">Daily Chg</th>
                      <th className="px-4 py-3 text-xs text-right"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700">
                    {assets
                      .filter(a => {
                        const q = assetFilter.toLowerCase();
                        return (!q || a.ticker.toLowerCase().includes(q) || a.primary_theme.toLowerCase().includes(q) || a.secondary_theme.toLowerCase().includes(q))
                          && (!primaryFilter || a.primary_theme === primaryFilter)
                          && (!secondaryFilter || a.secondary_theme === secondaryFilter);
                      })
                      .slice(assetPage * ASSETS_PER_PAGE, (assetPage + 1) * ASSETS_PER_PAGE)
                      .map((asset) => (
                        <tr key={asset.ticker} onClick={() => openTickerDetail(asset.ticker)} className={`hover:bg-gray-700/50 transition-colors cursor-pointer ${asset.price === 0 ? "bg-amber-900/10" : ""}`}>
                          <td className="px-4 py-2.5 font-medium text-white">
                            {asset.ticker}
                            {asset.price === 0 && <span className="ml-1.5 text-amber-400 text-xs">no price</span>}
                          </td>
                          <td className="px-4 py-2.5">
                            <button onClick={(e) => { e.stopPropagation(); setPrimaryFilter(asset.primary_theme); }} className="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-900/40 text-indigo-300 border border-indigo-700/50 hover:bg-indigo-900/60 transition-colors">{asset.primary_theme}</button>
                          </td>
                          <td className="px-4 py-2.5">
                            <button onClick={(e) => { e.stopPropagation(); setSecondaryFilter(asset.secondary_theme); }} className="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-900/40 text-cyan-300 border border-cyan-700/50 hover:bg-cyan-900/60 transition-colors">{asset.secondary_theme}</button>
                          </td>
                          <td className="px-4 py-2.5 text-right text-gray-300">${asset.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                          <td className="px-4 py-2.5 text-right">
                            {asset.daily_change_pct != null ? (
                              <span className={`font-medium ${asset.daily_change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                                {asset.daily_change_pct >= 0 ? "+" : ""}{asset.daily_change_pct.toFixed(2)}%
                              </span>
                            ) : <span className="text-gray-600 text-xs">--</span>}
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <button
                              onClick={async (e) => {
                                e.stopPropagation();
                                if (!confirm(`Remove "${asset.ticker}" from asset list?\n\nTrade history will be preserved.`)) return;
                                try {
                                  const res = await apiCall(`/api/assets/${asset.ticker}`, { method: "DELETE" });
                                  if (res.ok) refresh();
                                  else toast.error("Failed to remove asset.");
                                } catch { toast.error("Error removing asset."); }
                              }}
                              className="text-gray-500 hover:text-red-400 text-xs transition-colors"
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))}
                    {assets.length === 0 && (
                      <tr><td colSpan={6} className="px-6 py-8 text-center text-gray-500 italic">No assets. Add from <a href="/settings" className="text-indigo-400 hover:underline">Settings</a>.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              {(() => {
                const q = assetFilter.toLowerCase();
                const filteredCount = assets.filter(a =>
                  (!q || a.ticker.toLowerCase().includes(q) || a.primary_theme.toLowerCase().includes(q) || a.secondary_theme.toLowerCase().includes(q))
                  && (!primaryFilter || a.primary_theme === primaryFilter)
                  && (!secondaryFilter || a.secondary_theme === secondaryFilter)
                ).length;
                const totalPages = Math.ceil(filteredCount / ASSETS_PER_PAGE);
                if (totalPages <= 1) return null;
                return (
                  <div className="flex items-center justify-center gap-2 mt-3">
                    <button onClick={() => setAssetPage(p => Math.max(0, p - 1))} disabled={assetPage === 0}
                      className="px-3 py-1 rounded-md text-xs border border-gray-700 text-gray-400 hover:text-white hover:bg-gray-800 disabled:opacity-30 transition-colors">Prev</button>
                    <span className="text-xs text-gray-500">Page {assetPage + 1} of {totalPages}</span>
                    <button onClick={() => setAssetPage(p => Math.min(totalPages - 1, p + 1))} disabled={assetPage >= totalPages - 1}
                      className="px-3 py-1 rounded-md text-xs border border-gray-700 text-gray-400 hover:text-white hover:bg-gray-800 disabled:opacity-30 transition-colors">Next</button>
                  </div>
                );
              })()}
            </>
          )
        )}
      </div>

      {/* Ticker Detail Modal (trade history) */}
      {detailTicker && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50"
          onClick={(e) => { if (e.target === e.currentTarget) setDetailTicker(null); }}>
          <div className="bg-gray-800 rounded-xl shadow-xl border border-gray-700 w-full max-w-4xl max-h-[85vh] flex flex-col">
            <div className="flex justify-between items-center p-6 pb-4 border-b border-gray-700">
              <div>
                <h2 className="text-xl font-bold text-white">{detailTicker}</h2>
                <p className="text-xs text-gray-400 mt-1">{detailTrades.length} trades</p>
              </div>
              <button onClick={() => setDetailTicker(null)} className="text-gray-400 hover:text-white text-xl px-2 hover:bg-gray-700 rounded">&times;</button>
            </div>
            <div className="flex-1 overflow-auto p-6 pt-4">
              {detailLoading ? (
                <div className="flex justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500" />
                </div>
              ) : detailTrades.length === 0 ? (
                <p className="text-gray-500 text-sm italic py-4">No trades found for {detailTicker}.</p>
              ) : (
                <table className="min-w-full text-left text-sm whitespace-nowrap">
                  <thead className="text-gray-500 uppercase tracking-wider text-xs sticky top-0 bg-gray-800">
                    <tr>
                      <th className="px-3 py-2">Date</th>
                      <th className="px-3 py-2">Side</th>
                      <th className="px-3 py-2 text-right">Qty</th>
                      <th className="px-3 py-2 text-right">Price</th>
                      <th className="px-3 py-2 text-right">Total</th>
                      <th className="px-3 py-2 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-700/50">
                    {detailTrades.map((t, i) => (
                      <tr key={t.id || i} className="hover:bg-gray-700/30">
                        <td className="px-3 py-2 text-gray-300">{new Date(t.date).toLocaleDateString()}</td>
                        <td className={`px-3 py-2 font-semibold ${t.side === "Buy" ? "text-green-400" : "text-red-400"}`}>{t.side}</td>
                        <td className="px-3 py-2 text-right text-gray-300">{t.quantity.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right text-gray-300">${t.price.toFixed(2)}</td>
                        <td className="px-3 py-2 text-right text-white font-medium">${(t.quantity * t.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                        <td className="px-3 py-2 text-center">
                          {t.is_wash_sale && (
                            <span className="px-1.5 py-0.5 text-[10px] font-bold bg-red-600 text-red-100 rounded cursor-help"
                              title="IRS Wash Sale: sold at a loss and repurchased within 30 days.">WASH</span>
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

      {/* Edit Trade Modal */}
      {editingTrade && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50"
          onClick={(e) => { if (e.target === e.currentTarget) setEditingTrade(null); }}>
          <div className="bg-gray-800 rounded-lg shadow-xl border border-gray-700 w-full max-w-lg p-6">
            <h2 className="text-xl font-bold text-white mb-4">Edit Trade</h2>
            <form onSubmit={handleUpdate} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Date (YYYY-MM-DD)</label>
                  <input type="text" placeholder="2025-01-15"
                    value={(() => {
                      if (!editingTrade.date) return "";
                      if (editingTrade.date.length <= 10) return editingTrade.date;
                      try { const d = new Date(editingTrade.date); if (!isNaN(d.getTime())) return d.toISOString().slice(0, 10); } catch {}
                      return editingTrade.date;
                    })()}
                    onChange={(e) => {
                      const val = e.target.value;
                      if (/^\d{4}-\d{2}-\d{2}$/.test(val)) {
                        const d = new Date(val + "T12:00:00");
                        if (!isNaN(d.getTime())) { setEditingTrade({ ...editingTrade, date: d.toISOString() }); return; }
                      }
                      setEditingTrade({ ...editingTrade, date: val });
                    }}
                    className="w-full bg-gray-700 text-white rounded p-2 font-mono" />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Ticker</label>
                  <input type="text" value={editingTrade.ticker} onChange={(e) => setEditingTrade({ ...editingTrade, ticker: e.target.value })} className="w-full bg-gray-700 text-white rounded p-2 uppercase" />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Side</label>
                  <select value={editingTrade.side} onChange={(e) => setEditingTrade({ ...editingTrade, side: e.target.value })} className="w-full bg-gray-700 text-white rounded p-2">
                    <option value="Buy">Buy</option><option value="Sell">Sell</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Type</label>
                  <select value={editingTrade.type} onChange={(e) => setEditingTrade({ ...editingTrade, type: e.target.value })} className="w-full bg-gray-700 text-white rounded p-2">
                    <option value="Equity">Equity</option><option value="Option">Option</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Quantity</label>
                  <input type="number" step="any" value={editingTrade.quantity} onChange={(e) => setEditingTrade({ ...editingTrade, quantity: parseFloat(e.target.value) || 0 })} className="w-full bg-gray-700 text-white rounded p-2" />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">Price</label>
                  <input type="number" step="any" value={editingTrade.price} onChange={(e) => setEditingTrade({ ...editingTrade, price: parseFloat(e.target.value) || 0 })} className="w-full bg-gray-700 text-white rounded p-2" />
                </div>
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button type="button" onClick={() => setEditingTrade(null)} className="px-4 py-2 hover:bg-gray-700 rounded text-gray-300">Cancel</button>
                <button type="submit" className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-white">Save Changes</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}

export default function PortfolioPage() {
  return (
    <Suspense fallback={<main className="min-h-screen bg-gray-900 text-gray-100 p-8 flex justify-center items-center"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500" /></main>}>
      <PortfolioContent />
    </Suspense>
  );
}
