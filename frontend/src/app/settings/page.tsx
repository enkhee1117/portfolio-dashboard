"use client";

import { useState, useRef, useEffect } from "react";
import ImportButton from "../../components/ImportButton";

export default function SettingsPage() {
  // Last refresh timestamp
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const fetchLastRefresh = async () => {
    try {
      const res = await fetch("/api/assets/last-refresh");
      if (res.ok) {
        const data = await res.json();
        setLastRefresh(data.last_refresh);
      }
    } catch {}
  };

  useEffect(() => { fetchLastRefresh(); }, []);

  const formatLastRefresh = (iso: string | null) => {
    if (!iso) return "Never";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric", month: "long", day: "numeric",
    }) + " at " + d.toLocaleTimeString(undefined, {
      hour: "numeric", minute: "2-digit",
    });
  };

  // Refresh prices
  const [refreshing, setRefreshing] = useState(false);
  const [refreshResult, setRefreshResult] = useState<{
    message: string;
    updated: number;
    failed: string[];
  } | null>(null);

  // Export JSON
  const [exporting, setExporting] = useState(false);

  // Export CSV
  const [exportingCsv, setExportingCsv] = useState(false);

  // Restore
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState<{
    message: string;
    restored: { trades: number; assets: number };
  } | null>(null);
  const restoreInputRef = useRef<HTMLInputElement>(null);

  const handleRefreshPrices = async () => {
    setRefreshing(true);
    setRefreshResult(null);
    try {
      const res = await fetch("/api/assets/refresh-prices", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setRefreshResult(data);
        fetchLastRefresh();
      } else {
        setRefreshResult({ message: "Failed to refresh prices", updated: 0, failed: [] });
      }
    } catch {
      setRefreshResult({ message: "Error connecting to server", updated: 0, failed: [] });
    } finally {
      setRefreshing(false);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const res = await fetch("/api/backup/export");
      if (res.ok) {
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `portfolio_backup_${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } else {
        alert("Failed to export data.");
      }
    } catch {
      alert("Error exporting data.");
    } finally {
      setExporting(false);
    }
  };

  const handleExportCsv = async () => {
    setExportingCsv(true);
    try {
      const res = await fetch("/api/trades/export-csv");
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `trades_export_${new Date().toISOString().slice(0, 10)}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } else {
        alert("Failed to export CSV.");
      }
    } catch {
      alert("Error exporting CSV.");
    } finally {
      setExportingCsv(false);
    }
  };

  const handleRestore = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!confirm(
      "This will DELETE all existing trades and assets and replace them with the backup data. Are you sure?"
    )) {
      if (restoreInputRef.current) restoreInputRef.current.value = "";
      return;
    }

    setRestoring(true);
    setRestoreResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch("/api/backup/restore", {
        method: "POST",
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        setRestoreResult(data);
      } else {
        const err = await res.json().catch(() => ({}));
        alert(`Restore failed: ${err.detail || "Unknown error"}`);
      }
    } catch {
      alert("Error restoring backup.");
    } finally {
      setRestoring(false);
      if (restoreInputRef.current) restoreInputRef.current.value = "";
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

        {/* Export / Restore Backup */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <h3 className="text-lg font-semibold text-white mb-1">Backup &amp; Restore</h3>
          <p className="text-sm text-gray-400 mb-5">
            Export all trade history and asset themes as a JSON snapshot. Use restore to recover data from a backup.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Export */}
            <div className="bg-gray-900/50 rounded-lg p-4 border border-gray-700">
              <h4 className="text-sm font-medium text-white mb-1">Export Data</h4>
              <p className="text-xs text-gray-500 mb-3">
                Downloads a JSON file with all trades, asset themes, and prices.
              </p>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="w-full px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
              >
                {exporting ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                    Exporting...
                  </span>
                ) : (
                  "Export Backup"
                )}
              </button>
            </div>

            {/* Restore */}
            <div className="bg-gray-900/50 rounded-lg p-4 border border-gray-700">
              <h4 className="text-sm font-medium text-white mb-1">Restore Data</h4>
              <p className="text-xs text-gray-500 mb-3">
                Upload a backup JSON file to replace all current data.
              </p>
              <label
                className={`block w-full px-4 py-2.5 text-center rounded-lg text-sm font-medium transition-colors cursor-pointer ${
                  restoring
                    ? "bg-gray-600 text-gray-400 cursor-not-allowed"
                    : "bg-amber-600 hover:bg-amber-700 text-white"
                }`}
              >
                {restoring ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                    Restoring...
                  </span>
                ) : (
                  "Restore from Backup"
                )}
                <input
                  ref={restoreInputRef}
                  type="file"
                  accept=".json"
                  onChange={handleRestore}
                  disabled={restoring}
                  className="hidden"
                />
              </label>
            </div>
          </div>

          {/* Restore result */}
          {restoreResult && (
            <div className="mt-4 p-4 bg-green-900/20 rounded-lg border border-green-700/50">
              <p className="text-sm text-green-400 font-medium">{restoreResult.message}</p>
              <p className="text-xs text-gray-400 mt-1">
                {restoreResult.restored.trades} trades and {restoreResult.restored.assets} assets restored.
              </p>
            </div>
          )}
        </div>

        {/* Export Trades CSV */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="text-lg font-semibold text-white">Export Trades (CSV)</h3>
              <p className="text-sm text-gray-400 mt-1">
                Download all transactions as a CSV file for tax reporting or analysis in Excel.
                Includes date, ticker, side, quantity, price, total, themes, and wash sale flags.
              </p>
            </div>
            <button
              onClick={handleExportCsv}
              disabled={exportingCsv}
              className="shrink-0 ml-6 px-5 py-2.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
            >
              {exportingCsv ? (
                <span className="flex items-center gap-2">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                  Exporting...
                </span>
              ) : (
                "Download CSV"
              )}
            </button>
          </div>
        </div>

        {/* Refresh Prices */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="text-lg font-semibold text-white">Refresh Stock Prices</h3>
              <p className="text-sm text-gray-400 mt-1">
                Fetch latest closing prices from Yahoo Finance for all registered assets.
                Updates market values, unrealized P&L, daily change, and theme exposure.
              </p>
              <p className="text-xs mt-2">
                <span className="text-gray-500">Last refreshed: </span>
                <span className={lastRefresh ? "text-gray-300" : "text-amber-400"}>
                  {formatLastRefresh(lastRefresh)}
                </span>
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

        {/* About */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <h3 className="text-lg font-semibold text-white">About</h3>
          <p className="text-sm text-gray-400 mt-1">
            Portfolio Tracker uses Google Cloud Firestore for data storage and Yahoo Finance
            for live price data.
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
