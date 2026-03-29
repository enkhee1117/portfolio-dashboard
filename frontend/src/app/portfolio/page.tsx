"use client";

import { useEffect, useState, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import PositionTable from "../../components/PositionTable";
import { PortfolioSnapshot, Trade, Asset, ThemeLists } from "../types";
import { useToast } from "../../components/Toast";
import { useEscape, useCmdK } from "../../components/useKeyboard";

type TabType = "positions" | "trades" | "assets";

function PortfolioContent() {
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const initialTab: TabType = tabParam === "trades" ? "trades" : tabParam === "assets" ? "assets" : "positions";
  const [tab, setTab] = useState<TabType>(initialTab);

  // Positions
  const [positions, setPositions] = useState<PortfolioSnapshot[]>([]);
  const [posLoading, setPosLoading] = useState(true);

  // Trades
  const [trades, setTrades] = useState<Trade[]>([]);
  const [tradeLoading, setTradeLoading] = useState(true);

  // Assets
  const [assets, setAssets] = useState<Asset[]>([]);
  const [themes, setThemes] = useState<ThemeLists>({ primary: [], secondary: [] });
  const [assetLoading, setAssetLoading] = useState(true);
  const [assetFilter, setAssetFilter] = useState("");
  const [primaryFilter, setPrimaryFilter] = useState("");
  const [secondaryFilter, setSecondaryFilter] = useState("");

  const toast = useToast();
  useCmdK();

  const [filterText, setFilterText] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortKey, setSortKey] = useState<keyof Trade | null>("date");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [editingTrade, setEditingTrade] = useState<Trade | null>(null);

  useEscape(editingTrade ? () => setEditingTrade(null) : null);

  useEffect(() => {
    fetch("/api/portfolio")
      .then((r) => r.json())
      .then((data) => setPositions(data))
      .catch(console.error)
      .finally(() => setPosLoading(false));

    fetch("/api/trades")
      .then((r) => r.json())
      .then((data) => setTrades(data))
      .catch(console.error)
      .finally(() => setTradeLoading(false));

    Promise.all([fetch("/api/assets"), fetch("/api/assets/themes")])
      .then(async ([aRes, tRes]) => {
        if (aRes.ok) setAssets(await aRes.json());
        if (tRes.ok) setThemes(await tRes.json());
      })
      .catch(console.error)
      .finally(() => setAssetLoading(false));
  }, []);

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
      const res = await fetch(`/api/trades/${id}`, { method: "DELETE" });
      if (res.ok) setTrades(trades.filter((t) => t.id !== id));
      else toast.error("Failed to delete trade");
    } catch { toast.error("Error deleting trade"); }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingTrade) return;
    try {
      const res = await fetch(`/api/trades/${editingTrade.id}`, {
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
            <div className="flex justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500" />
            </div>
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
                            <div key={pos.ticker} className="flex items-center justify-between py-0.5">
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
                            <div key={pos.ticker} className="flex items-center justify-between py-0.5">
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
              <div className="flex justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500" />
              </div>
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
            <div className="flex justify-center py-12"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500" /></div>
          ) : (
            <>
              <div className="flex items-center gap-3 flex-wrap">
                <input type="text" placeholder="Search ticker or theme..." value={assetFilter} onChange={(e) => setAssetFilter(e.target.value)}
                  className="bg-gray-800 text-white px-4 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 w-full md:w-64 text-sm" />
                <select value={primaryFilter} onChange={(e) => setPrimaryFilter(e.target.value)} className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 text-sm">
                  <option value="">All Primary</option>
                  {themes.primary.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                <select value={secondaryFilter} onChange={(e) => setSecondaryFilter(e.target.value)} className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 text-sm">
                  <option value="">All Secondary</option>
                  {themes.secondary.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                {(assetFilter || primaryFilter || secondaryFilter) && (
                  <button onClick={() => { setAssetFilter(""); setPrimaryFilter(""); setSecondaryFilter(""); }} className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700">Clear</button>
                )}
                <span className="text-xs text-gray-500 ml-auto">
                  {assets.filter(a => {
                    const q = assetFilter.toLowerCase();
                    return (!q || a.ticker.toLowerCase().includes(q) || a.primary_theme.toLowerCase().includes(q) || a.secondary_theme.toLowerCase().includes(q))
                      && (!primaryFilter || a.primary_theme === primaryFilter)
                      && (!secondaryFilter || a.secondary_theme === secondaryFilter);
                  }).length} of {assets.length}
                </span>
              </div>
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
                      .map((asset) => (
                        <tr key={asset.ticker} className="hover:bg-gray-700/50 transition-colors">
                          <td className="px-4 py-2.5 font-medium text-white">{asset.ticker}</td>
                          <td className="px-4 py-2.5">
                            <button onClick={() => setPrimaryFilter(asset.primary_theme)} className="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-900/40 text-indigo-300 border border-indigo-700/50 hover:bg-indigo-900/60 transition-colors">{asset.primary_theme}</button>
                          </td>
                          <td className="px-4 py-2.5">
                            <button onClick={() => setSecondaryFilter(asset.secondary_theme)} className="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-900/40 text-cyan-300 border border-cyan-700/50 hover:bg-cyan-900/60 transition-colors">{asset.secondary_theme}</button>
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
                              onClick={async () => {
                                if (!confirm(`Remove "${asset.ticker}" from asset list?\n\nTrade history will be preserved.`)) return;
                                try {
                                  const res = await fetch(`/api/assets/${asset.ticker}`, { method: "DELETE" });
                                  if (res.ok) setAssets(assets.filter(a => a.ticker !== asset.ticker));
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
            </>
          )
        )}
      </div>

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
