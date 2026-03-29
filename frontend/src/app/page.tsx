"use client";

import { useEffect, useState, useMemo } from 'react';
import PositionTable from '../components/PositionTable';
import ManualTradeForm from '../components/ManualTradeForm';
import ThemeAnalysis from '../components/ThemeAnalysis';
import PortfolioChart from '../components/PortfolioChart';
import { PortfolioSnapshot, ThemeLists } from './types';
import { useToast } from '../components/Toast';
import { useCmdK } from '../components/useKeyboard';

export default function Home() {
  const [positions, setPositions] = useState<PortfolioSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [showManualTrade, setShowManualTrade] = useState(false);
  const [pnlView, setPnlView] = useState<'ytd' | 'all'>('ytd');

  const toast = useToast();
  useCmdK();

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
      const res = await fetch('/api/portfolio');
      if (res.ok) {
        const data = await res.json();
        setPositions(data);
      } else {
        console.error('Failed to fetch portfolio');
      }
    } catch (error) {
      console.error('Error fetching portfolio:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPortfolio();
  }, []);

  const totalMarketValue = positions.reduce((acc, pos) => acc + pos.market_value, 0);
  const totalUnrealized = positions.reduce((acc, pos) => acc + pos.unrealized_pnl, 0);
  const totalRealized = positions.reduce((acc, pos) => acc + pos.realized_pnl, 0);
  const totalRealizedYtd = positions.reduce((acc, pos) => acc + (pos.realized_pnl_ytd || 0), 0);
  const totalPnL = totalUnrealized + totalRealized;
  const totalPnLYtd = totalUnrealized + totalRealizedYtd;

  // Display values based on toggle
  const displayRealized = pnlView === 'ytd' ? totalRealizedYtd : totalRealized;
  const displayTotalPnl = pnlView === 'ytd' ? totalPnLYtd : totalPnL;

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
    try {
      const res = await fetch('/api/assets/themes');
      if (res.ok) setThemes(await res.json());
    } catch {}
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
      let res = await fetch(`/api/assets/${ticker}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ primary_theme: form.primary, secondary_theme: form.secondary }),
      });
      if (res.status === 404) {
        res = await fetch('/api/assets', {
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
            onClick={() => setShowManualTrade(!showManualTrade)}
            className="px-4 py-2 border border-gray-600 rounded-md hover:bg-gray-800 text-gray-300 text-sm transition-colors"
          >
            {showManualTrade ? 'Hide Form' : 'Add Trade'}
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

        {/* Manual Trade Form */}
        {showManualTrade && (
          <ManualTradeForm onTradeAdded={fetchPortfolio} />
        )}

        {/* Theme Analysis */}
        <ThemeAnalysis positions={positions} />

        {/* Current Positions */}
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-lg font-semibold text-gray-200">Current Positions</h2>
            <span className="text-sm text-gray-400">{positions.length} positions</span>
          </div>

          {loading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500"></div>
            </div>
          ) : (
            <PositionTable positions={positions} />
          )}
        </div>

      </div>
    </main>
  );
}
