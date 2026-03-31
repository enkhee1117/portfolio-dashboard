"use client";

import { useEffect, useState, useMemo } from 'react';
import ManualTradeForm from '../components/ManualTradeForm';
import ThemeAnalysis from '../components/ThemeAnalysis';
import PortfolioChart from '../components/PortfolioChart';
import { PortfolioSnapshot, ThemeLists, Asset } from './types';
import { useToast } from '../components/Toast';
import { apiCall } from "../lib/api";
import { useAuth } from "../lib/AuthContext";
import { useCmdK, useEscape } from '../components/useKeyboard';

export default function Home() {
  const [positions, setPositions] = useState<PortfolioSnapshot[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [showManualTrade, setShowManualTrade] = useState(false);
  const [pnlView, setPnlView] = useState<'ytd' | 'all'>('ytd');

  const { user } = useAuth();
  const toast = useToast();
  useCmdK();
  useEscape(showManualTrade ? () => setShowManualTrade(false) : null);

  const copyValue = (val: number) => {
    navigator.clipboard.writeText(val.toFixed(2));
    toast.info("Copied to clipboard");
  };

  // Missing themes panel
  const [showMissing, setShowMissing] = useState(false);
  const [themes, setThemes] = useState<ThemeLists>({ primary: [], secondary: [] });
  const [fixForms, setFixForms] = useState<Record<string, { primary: string; secondary: string }>>({});
  const [savingTicker, setSavingTicker] = useState<string | null>(null);

  const fetchPortfolio = async () => {
    setLoading(true);
    try {
      const res = await apiCall('/api/portfolio');
      if (res.ok) {
        const data = await res.json();
        setPositions(data);
      } else {
        console.warn('Failed to fetch portfolio');
      }
    } catch (error) {
      console.error('Error fetching portfolio:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!user) return;
    fetchPortfolio();
    apiCall("/api/assets").then(async r => { if (r.ok) setAssets(await r.json()); }).catch(console.error);
  }, [user]);

  const totalMarketValue = positions.reduce((acc, pos) => acc + pos.market_value, 0);
  const totalUnrealized = positions.reduce((acc, pos) => acc + pos.unrealized_pnl, 0);
  const totalRealized = positions.reduce((acc, pos) => acc + pos.realized_pnl, 0);
  const totalRealizedYtd = positions.reduce((acc, pos) => acc + (pos.realized_pnl_ytd || 0), 0);
  const totalPnL = totalUnrealized + totalRealized;
  const totalPnLYtd = totalUnrealized + totalRealizedYtd;

  // Cost basis = total capital deployed in current holdings
  const totalCostBasis = positions.reduce((acc, pos) => acc + (pos.quantity > 0 ? pos.average_price * pos.quantity : 0), 0);

  // Display values based on toggle
  const displayRealized = pnlView === 'ytd' ? totalRealizedYtd : totalRealized;
  const displayTotalPnl = pnlView === 'ytd' ? totalPnLYtd : totalPnL;
  const displayPnlPct = totalCostBasis > 0 ? (displayTotalPnl / totalCostBasis) * 100 : 0;

  const activePositions = useMemo(() => positions.filter(p => p.quantity > 0), [positions]);
  const unassignedPositions = useMemo(
    () => activePositions.filter(p => !p.primary_theme || !p.secondary_theme),
    [activePositions]
  );

  // When "missing themes" is clicked, fetch theme suggestions and init forms
  const handleShowMissing = async () => {
    if (showMissing) {
      setShowMissing(false);
      return;
    }
    // Derive themes from already-loaded assets instead of a separate API call
    const primary = new Set<string>();
    const secondary = new Set<string>();
    assets.forEach(a => {
      if (a.primary_theme) primary.add(a.primary_theme);
      if (a.secondary_theme) secondary.add(a.secondary_theme);
    });
    setThemes({ primary: [...primary].sort(), secondary: [...secondary].sort() });
    // Init fix forms for each unassigned ticker
    const forms: Record<string, { primary: string; secondary: string }> = {};
    unassignedPositions.forEach(p => {
      forms[p.ticker] = { primary: p.primary_theme || '', secondary: p.secondary_theme || '' };
    });
    setFixForms(forms);
    setShowMissing(true);
  };

  // Save themes for a single ticker
  const handleFixTheme = async (ticker: string) => {
    const form = fixForms[ticker];
    if (!form?.primary || !form?.secondary) {
      toast.error('Both primary and secondary themes are required.');
      return;
    }
    setSavingTicker(ticker);
    try {
      // Try PUT first (asset exists but themes are null), fall back to POST (asset doesn't exist)
      let res = await apiCall(`/api/assets/${ticker}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ primary_theme: form.primary, secondary_theme: form.secondary }),
      });
      if (res.status === 404) {
        res = await apiCall('/api/assets', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ticker,
            primary_theme: form.primary,
            secondary_theme: form.secondary,
            price: 0,
          }),
        });
      }
      if (res.ok) {
        // Remove from list and refresh portfolio
        const newForms = { ...fixForms };
        delete newForms[ticker];
        setFixForms(newForms);
        fetchPortfolio();
      } else {
        toast.error('Failed to save themes.');
      }
    } catch {
      toast.error('Error saving themes.');
    } finally {
      setSavingTicker(null);
    }
  };

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">

        {/* Page Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="mt-1 text-sm text-gray-400">Portfolio overview and P&L analysis</p>
          </div>
          <button
            onClick={() => setShowManualTrade(true)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-md transition-colors"
          >
            + Add Trade
          </button>
        </div>

        {/* P&L Period Toggle + Summary Cards */}
        <div className="flex items-center justify-between">
          <div className="flex gap-1 bg-gray-800 rounded-lg p-0.5 border border-gray-700">
            <button
              onClick={() => setPnlView('ytd')}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                pnlView === 'ytd' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              YTD
            </button>
            <button
              onClick={() => setPnlView('all')}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
                pnlView === 'all' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-200'
              }`}
            >
              All Time
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div onClick={() => copyValue(totalMarketValue)} className="bg-gray-800 rounded-xl p-5 shadow-lg border border-gray-700 cursor-pointer hover:border-gray-600 transition-colors group" title="Click to copy">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-widest group-hover:text-gray-300">Net Liquidity</h3>
            <p className="mt-2 text-2xl font-bold text-white">
              ${totalMarketValue.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </p>
          </div>
          <div onClick={() => copyValue(displayTotalPnl)} className="bg-gray-800 rounded-xl p-5 shadow-lg border border-gray-700 cursor-pointer hover:border-gray-600 transition-colors group" title="Click to copy">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-widest group-hover:text-gray-300">
              {pnlView === 'ytd' ? 'YTD P&L' : 'Total P&L'}
            </h3>
            <p className={`mt-2 text-2xl font-bold ${displayTotalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${displayTotalPnl.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </p>
            <p className={`text-xs mt-1 ${displayPnlPct >= 0 ? 'text-green-400/70' : 'text-red-400/70'}`}>
              {displayPnlPct >= 0 ? '+' : ''}{displayPnlPct.toFixed(1)}% on cost
            </p>
          </div>
          <div onClick={() => copyValue(totalUnrealized)} className="bg-gray-800 rounded-xl p-5 shadow-lg border border-gray-700 cursor-pointer hover:border-gray-600 transition-colors group" title="Click to copy">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-widest group-hover:text-gray-300">Unrealized</h3>
            <p className={`mt-2 text-2xl font-bold ${totalUnrealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${totalUnrealized.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </p>
          </div>
          <div onClick={() => copyValue(displayRealized)} className="bg-gray-800 rounded-xl p-5 shadow-lg border border-gray-700 cursor-pointer hover:border-gray-600 transition-colors group" title="Click to copy">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-widest group-hover:text-gray-300">
              {pnlView === 'ytd' ? 'Realized YTD' : 'Realized All'}
            </h3>
            <p className={`mt-2 text-2xl font-bold ${displayRealized >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${displayRealized.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </p>
          </div>
        </div>

        {/* Quick Stats Row */}
        <div className="flex gap-4 text-sm">
          <span className="px-3 py-1.5 bg-gray-800 rounded-lg border border-gray-700 text-gray-300">
            {activePositions.length} active positions
          </span>
          {unassignedPositions.length > 0 && (
            <button
              onClick={handleShowMissing}
              className="px-3 py-1.5 bg-amber-900/30 rounded-lg border border-amber-700/50 text-amber-300 hover:bg-amber-900/50 transition-colors"
            >
              {unassignedPositions.length} stock{unassignedPositions.length !== 1 ? 's' : ''} missing themes
            </button>
          )}
        </div>

        {/* Missing Themes Panel */}
        {showMissing && unassignedPositions.length > 0 && (
          <div className="bg-amber-900/20 border border-amber-700/50 rounded-xl p-6">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-lg font-semibold text-amber-300">
                Assign Missing Themes
              </h3>
              <button
                onClick={() => setShowMissing(false)}
                className="text-sm text-gray-400 hover:text-white px-3 py-1 rounded hover:bg-gray-700"
              >
                Close
              </button>
            </div>
            <div className="space-y-3">
              {unassignedPositions.map(pos => {
                const form = fixForms[pos.ticker] || { primary: '', secondary: '' };
                const isSaving = savingTicker === pos.ticker;
                return (
                  <div
                    key={pos.ticker}
                    className="flex items-center gap-3 bg-gray-800/60 rounded-lg p-3 border border-gray-700/50"
                  >
                    <span className="text-white font-medium w-20 shrink-0">{pos.ticker}</span>
                    <span className="text-gray-500 text-xs w-24 shrink-0">
                      ${pos.market_value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                    </span>
                    <input
                      type="text"
                      list="fix-primary-themes"
                      placeholder="Primary theme"
                      value={form.primary}
                      onChange={e =>
                        setFixForms({ ...fixForms, [pos.ticker]: { ...form, primary: e.target.value } })
                      }
                      className="flex-1 bg-gray-700 text-white px-3 py-1.5 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none text-sm"
                    />
                    <input
                      type="text"
                      list="fix-secondary-themes"
                      placeholder="Secondary theme"
                      value={form.secondary}
                      onChange={e =>
                        setFixForms({ ...fixForms, [pos.ticker]: { ...form, secondary: e.target.value } })
                      }
                      className="flex-1 bg-gray-700 text-white px-3 py-1.5 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none text-sm"
                    />
                    <button
                      onClick={() => handleFixTheme(pos.ticker)}
                      disabled={isSaving}
                      className="px-4 py-1.5 bg-amber-600 hover:bg-amber-700 text-white rounded text-sm font-medium transition-colors disabled:opacity-50 shrink-0"
                    >
                      {isSaving ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                );
              })}
            </div>
            <datalist id="fix-primary-themes">
              {themes.primary.map(t => <option key={t} value={t} />)}
            </datalist>
            <datalist id="fix-secondary-themes">
              {themes.secondary.map(t => <option key={t} value={t} />)}
            </datalist>
          </div>
        )}

        {/* Welcome banner for new users */}
        {!loading && activePositions.length === 0 && (
          <div className="bg-indigo-900/20 border border-indigo-700/50 rounded-xl p-6 text-center">
            <h3 className="text-lg font-semibold text-white mb-2">Welcome to Portfolio Tracker</h3>
            <p className="text-sm text-gray-400 mb-4">
              Get started by importing your trade history or adding your first trade.
            </p>
            <div className="flex justify-center gap-3">
              <a
                href="/settings"
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-md transition-colors"
              >
                Import Data
              </a>
              <button
                onClick={() => setShowManualTrade(true)}
                className="px-4 py-2 border border-gray-600 hover:bg-gray-800 text-gray-300 text-sm rounded-md transition-colors"
              >
                Add First Trade
              </button>
            </div>
          </div>
        )}

        {/* Portfolio History Chart */}
        <PortfolioChart />

        {/* Manual Trade Form — Modal */}
        {showManualTrade && (
          <div
            className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50"
            onClick={(e) => { if (e.target === e.currentTarget) setShowManualTrade(false); }}
          >
            <div className="bg-gray-900 rounded-xl shadow-xl border border-gray-700 w-full max-w-2xl">
              <div className="flex justify-between items-center px-6 pt-5 pb-0">
                <h2 className="text-lg font-bold text-white">Add Trade</h2>
                <button onClick={() => setShowManualTrade(false)} className="text-gray-400 hover:text-white text-xl px-2 hover:bg-gray-700 rounded">&times;</button>
              </div>
              <ManualTradeForm onTradeAdded={() => { fetchPortfolio(); setShowManualTrade(false); }} />
            </div>
          </div>
        )}

        {/* Theme Analysis */}
        <ThemeAnalysis positions={positions} />

        {/* Top Positions */}
        <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold text-gray-200">Top Positions</h2>
            <a
              href="/portfolio"
              className="text-sm text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              View all {activePositions.length} &rarr;
            </a>
          </div>

          {loading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-500"></div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm whitespace-nowrap">
                <thead className="text-gray-500 uppercase tracking-wider text-xs border-b border-gray-700">
                  <tr>
                    <th className="px-3 py-2">Ticker</th>
                    <th className="px-3 py-2 hidden sm:table-cell">Theme</th>
                    <th className="px-3 py-2 text-right">Mkt Value</th>
                    <th className="px-3 py-2 text-right">Unreal. P&L</th>
                    <th className="px-3 py-2 text-right hidden sm:table-cell">% Portfolio</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {activePositions
                    .sort((a, b) => b.market_value - a.market_value)
                    .slice(0, 10)
                    .map((pos) => {
                      const pctPortfolio = totalMarketValue > 0 ? (pos.market_value / totalMarketValue) * 100 : 0;
                      return (
                        <tr key={pos.ticker} className="hover:bg-gray-700/30">
                          <td className="px-3 py-2.5 font-medium text-white">{pos.ticker}</td>
                          <td className="px-3 py-2.5 hidden sm:table-cell">
                            {pos.primary_theme && (
                              <span className="px-1.5 py-0.5 rounded text-xs bg-indigo-900/40 text-indigo-300 border border-indigo-700/50">
                                {pos.primary_theme}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-right text-white font-medium">
                            ${pos.market_value.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                          </td>
                          <td className={`px-3 py-2.5 text-right font-medium ${pos.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                            ${pos.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                          </td>
                          <td className="px-3 py-2.5 text-right text-gray-400 hidden sm:table-cell">
                            {pctPortfolio.toFixed(1)}%
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Daily Movers */}
        {assets.filter(a => a.daily_change_pct != null).length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Biggest Daily Gainers */}
            <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
              <h3 className="text-sm font-semibold text-green-400 uppercase tracking-widest mb-3">Daily Gainers</h3>
              <div className="space-y-2">
                {assets
                  .filter(a => a.daily_change_pct != null && a.daily_change_pct! > 0)
                  .sort((a, b) => (b.daily_change_pct || 0) - (a.daily_change_pct || 0))
                  .slice(0, 5)
                  .map(a => (
                    <div key={a.ticker} className="flex items-center justify-between py-1">
                      <div className="flex items-center gap-2">
                        <span className="text-white font-medium text-sm">{a.ticker}</span>
                        <span className="text-xs text-gray-500">${a.price.toFixed(2)}</span>
                      </div>
                      <span className="text-green-400 text-sm font-medium">+{a.daily_change_pct!.toFixed(2)}%</span>
                    </div>
                  ))}
                {assets.filter(a => a.daily_change_pct != null && a.daily_change_pct! > 0).length === 0 && (
                  <p className="text-gray-500 text-xs italic">No gainers today</p>
                )}
              </div>
            </div>

            {/* Biggest Daily Losers */}
            <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
              <h3 className="text-sm font-semibold text-red-400 uppercase tracking-widest mb-3">Daily Losers</h3>
              <div className="space-y-2">
                {assets
                  .filter(a => a.daily_change_pct != null && a.daily_change_pct! < 0)
                  .sort((a, b) => (a.daily_change_pct || 0) - (b.daily_change_pct || 0))
                  .slice(0, 5)
                  .map(a => (
                    <div key={a.ticker} className="flex items-center justify-between py-1">
                      <div className="flex items-center gap-2">
                        <span className="text-white font-medium text-sm">{a.ticker}</span>
                        <span className="text-xs text-gray-500">${a.price.toFixed(2)}</span>
                      </div>
                      <span className="text-red-400 text-sm font-medium">{a.daily_change_pct!.toFixed(2)}%</span>
                    </div>
                  ))}
                {assets.filter(a => a.daily_change_pct != null && a.daily_change_pct! < 0).length === 0 && (
                  <p className="text-gray-500 text-xs italic">No losers today</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* RSI Signals */}
        {assets.filter(a => a.rsi != null).length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Overbought */}
            <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
              <h3 className="text-sm font-semibold text-amber-400 uppercase tracking-widest mb-1">Overbought (RSI &gt; 70)</h3>
              <p className="text-xs text-gray-500 mb-3">May be due for a pullback</p>
              <div className="space-y-1.5">
                {assets
                  .filter(a => a.rsi != null && a.rsi! > 70)
                  .sort((a, b) => (b.rsi || 0) - (a.rsi || 0))
                  .slice(0, 10)
                  .map(a => (
                    <div key={a.ticker} className="flex items-center justify-between py-0.5">
                      <div className="flex items-center gap-2">
                        <span className="text-white font-medium text-sm">{a.ticker}</span>
                        <span className="text-xs text-gray-500">${a.price.toFixed(2)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                          <div className="h-full bg-amber-500 rounded-full" style={{ width: `${a.rsi}%` }} />
                        </div>
                        <span className="text-amber-400 text-sm font-medium w-10 text-right">{a.rsi}</span>
                      </div>
                    </div>
                  ))}
                {assets.filter(a => a.rsi != null && a.rsi! > 70).length === 0 && (
                  <p className="text-gray-500 text-xs italic">No overbought assets</p>
                )}
              </div>
            </div>

            {/* Oversold */}
            <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
              <h3 className="text-sm font-semibold text-cyan-400 uppercase tracking-widest mb-1">Oversold (RSI &lt; 30)</h3>
              <p className="text-xs text-gray-500 mb-3">May be a buying opportunity</p>
              <div className="space-y-1.5">
                {assets
                  .filter(a => a.rsi != null && a.rsi! < 30)
                  .sort((a, b) => (a.rsi || 0) - (b.rsi || 0))
                  .slice(0, 10)
                  .map(a => (
                    <div key={a.ticker} className="flex items-center justify-between py-0.5">
                      <div className="flex items-center gap-2">
                        <span className="text-white font-medium text-sm">{a.ticker}</span>
                        <span className="text-xs text-gray-500">${a.price.toFixed(2)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                          <div className="h-full bg-cyan-500 rounded-full" style={{ width: `${a.rsi}%` }} />
                        </div>
                        <span className="text-cyan-400 text-sm font-medium w-10 text-right">{a.rsi}</span>
                      </div>
                    </div>
                  ))}
                {assets.filter(a => a.rsi != null && a.rsi! < 30).length === 0 && (
                  <p className="text-gray-500 text-xs italic">No oversold assets</p>
                )}
              </div>
            </div>
          </div>
        )}

      </div>
    </main>
  );
}
