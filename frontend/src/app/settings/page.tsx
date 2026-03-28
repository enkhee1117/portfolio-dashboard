"use client";

import { useState } from "react";
import ImportButton from "../../components/ImportButton";

export default function SettingsPage() {
  // Refresh prices
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState<{
    message: string;
    updated: number;
    failed: string[];
  } | null>(null);

  const handleRefreshPrices = async () => {
    setRefreshing(true);
    setRefreshResult(null);
    try {
      const res = await fetch("/api/assets/refresh-prices", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setRefreshResult(data);
      } else {
        setRefreshResult({ message: "Failed to refresh prices", updated: 0, failed: [] });
      }
    } catch {
      setRefreshResult({ message: "Error connecting to server", updated: 0, failed: [] });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-3xl mx-auto space-y-8">
        {/* Page Header */}
        <div>
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="mt-1 text-sm text-gray-400">
            Data management and portfolio maintenance
          </p>
        </div>

        {/* Refresh Prices */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="text-lg font-semibold text-white">Refresh Stock Prices</h3>
              <p className="text-sm text-gray-400 mt-1">
                Fetch latest closing prices from Yahoo Finance for all registered assets.
                Updates market values, unrealized P&L, and theme exposure calculations.
              </p>
            </div>
            <button
              onClick={handleRefreshPrices}
              disabled={refreshing}
              className="shrink-0 ml-6 px-5 py-2.5 bg-cyan-600 hover:bg-cyan-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {refreshing ? (
                <span className="flex items-center gap-2">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                  Refreshing...
                </span>
              ) : (
                "Refresh Prices"
              )}
            </button>
          </div>

          {/* Result */}
          {refreshResult && (
            <div className="mt-4 p-4 bg-gray-900/50 rounded-lg border border-gray-700">
              <p className="text-sm text-green-400 font-medium">{refreshResult.message}</p>
              {refreshResult.failed.length > 0 && (
                <details className="mt-2">
                  <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-300">
                    {refreshResult.failed.length} tickers failed (click to see)
                  </summary>
                  <p className="mt-2 text-xs text-gray-500 leading-relaxed">
                    {refreshResult.failed.join(", ")}
                  </p>
                </details>
              )}
            </div>
          )}
        </div>

        {/* Import Data */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="text-lg font-semibold text-white">Import Data</h3>
              <p className="text-sm text-gray-400 mt-1">
                Upload Excel or CSV files to import trade history or portfolio snapshots
                (themes and prices).
              </p>
              <div className="mt-3 space-y-2">
                <div className="flex items-start gap-2 text-xs text-gray-500">
                  <span className="text-indigo-400 mt-0.5">1.</span>
                  <span>
                    <strong className="text-gray-300">Trade History</strong> &mdash; CSV with
                    columns: Assets, Date, Ticker, Price, Number of stocks. Imports buy/sell
                    trades with deduplication.
                  </span>
                </div>
                <div className="flex items-start gap-2 text-xs text-gray-500">
                  <span className="text-indigo-400 mt-0.5">2.</span>
                  <span>
                    <strong className="text-gray-300">Portfolio Snapshot</strong> &mdash; CSV
                    with columns: Assets, Ticker, Primary theme, Secondary theme, Price.
                    Updates asset registry with themes and prices.
                  </span>
                </div>
              </div>
            </div>
            <div className="shrink-0 ml-6">
              <ImportButton onImportSuccess={() => {}} />
            </div>
          </div>
        </div>

        {/* Data Info */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <h3 className="text-lg font-semibold text-white">About</h3>
          <p className="text-sm text-gray-400 mt-1">
            Portfolio Tracker uses Google Cloud Firestore for data storage and Yahoo Finance
            for live price data. Deployed on Vercel.
          </p>
          <div className="mt-4 grid grid-cols-2 gap-4 text-xs">
            <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700">
              <span className="text-gray-500">Price Source</span>
              <p className="text-gray-300 mt-0.5">Yahoo Finance</p>
            </div>
            <div className="bg-gray-900/50 rounded-lg p-3 border border-gray-700">
              <span className="text-gray-500">Database</span>
              <p className="text-gray-300 mt-0.5">Google Firestore</p>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
