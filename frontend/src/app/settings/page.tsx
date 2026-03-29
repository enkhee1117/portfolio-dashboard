"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import ImportButton from "../../components/ImportButton";
import { useToast } from "../../components/Toast";

export default function SettingsPage() {
  const toast = useToast();

  // Refresh status
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const [nextScheduled, setNextScheduled] = useState<string | null>(null);
  const [schedule, setSchedule] = useState<string>("");

  const fetchRefreshStatus = async () => {
    try {
      const res = await fetch("/api/assets/refresh-status");
      if (res.ok) {
        const data = await res.json();
        setLastRefresh(data.last_refresh);
        setNextScheduled(data.next_scheduled);
        setSchedule(data.schedule || "");
      }
    } catch {}
  };

  useEffect(() => { fetchRefreshStatus(); }, []);

  const formatTimestamp = (iso: string | null) => {
    if (!iso) return "Never";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric", month: "long", day: "numeric",
    }) + " at " + d.toLocaleTimeString(undefined, {
      hour: "numeric", minute: "2-digit",
    });
  };

  // Manual refresh
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

  // Theme management
  const [themeSummary, setThemeSummary] = useState<{
    primary: { name: string; count: number }[];
    secondary: { name: string; count: number }[];
  }>({ primary: [], secondary: [] });
  const [renamingTheme, setRenamingTheme] = useState<{ name: string; field: string } | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [combineMode, setCombineMode] = useState<{ field: "primary" | "secondary" } | null>(null);
  const [combineSource, setCombineSource] = useState("");
  const [combineTarget, setCombineTarget] = useState("");

  const fetchThemeSummary = async () => {
    try {
      const res = await fetch("/api/themes/summary");
      if (res.ok) setThemeSummary(await res.json());
    } catch {}
  };

  useEffect(() => { fetchThemeSummary(); }, []);

  const handleRenameTheme = async () => {
    if (!renamingTheme || !renameValue.trim()) return;
    const res = await fetch("/api/themes/rename", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_name: renamingTheme.name, new_name: renameValue.trim(), field: renamingTheme.field }),
    });
    if (res.ok) {
      const data = await res.json();
      toast.success(data.message);
      setRenamingTheme(null);
      setRenameValue("");
      fetchThemeSummary();
    } else toast.error("Failed to rename theme.");
  };

  const handleDeleteTheme = async (name: string, field: string) => {
    if (!confirm(`Remove "${name}" from all assets? Affected assets will show as "Unassigned".`)) return;
    const res = await fetch(`/api/themes/${encodeURIComponent(name)}?field=${field}`, { method: "DELETE" });
    if (res.ok) {
      const data = await res.json();
      toast.success(data.message);
      fetchThemeSummary();
    } else toast.error("Failed to delete theme.");
  };

  const handleCombine = async () => {
    if (!combineMode || !combineSource || !combineTarget) return;
    if (combineSource === combineTarget) { toast.error("Source and target are the same."); return; }
    if (!confirm(`Merge "${combineSource}" into "${combineTarget}"? All assets with "${combineSource}" will be reassigned.`)) return;
    const res = await fetch("/api/themes/combine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source: combineSource, target: combineTarget, field: combineMode.field }),
    });
    if (res.ok) {
      const data = await res.json();
      toast.success(data.message);
      setCombineMode(null);
      setCombineSource("");
      setCombineTarget("");
      fetchThemeSummary();
    } else toast.error("Failed to combine themes.");
  };

  const handleRefreshPrices = async () => {
    setRefreshing(true);
    setRefreshResult(null);
    try {
      const res = await fetch("/api/assets/refresh-prices", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setRefreshResult(data);
        fetchRefreshStatus();
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
        toast.error("Failed to export data.");
      }
    } catch {
      toast.error("Error exporting data.");
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
        toast.error("Failed to export CSV.");
      }
    } catch {
      toast.error("Error exporting CSV.");
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
        toast.error(`Restore failed: ${err.detail || "Unknown error"}`);
      }
    } catch {
      toast.error("Error restoring backup.");
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

        {/* Theme Management */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg">
          <h3 className="text-lg font-semibold text-white mb-1">Theme Management</h3>
          <p className="text-sm text-gray-400 mb-5">
            Rename, delete, or combine investment themes across all assets.
          </p>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Primary Themes */}
            {(["primary", "secondary"] as const).map((field) => {
              const themes = field === "primary" ? themeSummary.primary : themeSummary.secondary;
              const label = field === "primary" ? "Primary" : "Secondary";
              return (
                <div key={field}>
                  <div className="flex justify-between items-center mb-3">
                    <h4 className="text-sm font-semibold text-gray-300">{label} Themes ({themes.length})</h4>
                    <button
                      onClick={() => {
                        if (combineMode?.field === field) setCombineMode(null);
                        else { setCombineMode({ field }); setCombineSource(""); setCombineTarget(""); }
                      }}
                      className={`text-xs px-2 py-1 rounded transition-colors ${
                        combineMode?.field === field
                          ? "bg-indigo-600 text-white"
                          : "text-gray-400 hover:text-white hover:bg-gray-700"
                      }`}
                    >
                      {combineMode?.field === field ? "Cancel Combine" : "Combine"}
                    </button>
                  </div>

                  {/* Combine UI */}
                  {combineMode?.field === field && (
                    <div className="mb-3 p-3 bg-indigo-900/20 border border-indigo-700/50 rounded-lg">
                      <p className="text-xs text-indigo-300 mb-2">Merge one theme into another:</p>
                      <div className="flex gap-2 items-center">
                        <select value={combineSource} onChange={(e) => setCombineSource(e.target.value)} className="bg-gray-700 text-white px-2 py-1.5 rounded border border-gray-600 text-xs flex-1">
                          <option value="">Source (will be removed)</option>
                          {themes.map((t) => <option key={t.name} value={t.name}>{t.name} ({t.count})</option>)}
                        </select>
                        <span className="text-gray-500 text-xs">&rarr;</span>
                        <select value={combineTarget} onChange={(e) => setCombineTarget(e.target.value)} className="bg-gray-700 text-white px-2 py-1.5 rounded border border-gray-600 text-xs flex-1">
                          <option value="">Target (will keep)</option>
                          {themes.map((t) => <option key={t.name} value={t.name}>{t.name} ({t.count})</option>)}
                        </select>
                        <button onClick={handleCombine} disabled={!combineSource || !combineTarget} className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-xs disabled:opacity-50">
                          Merge
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Theme list */}
                  <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-700">
                    {themes.length === 0 ? (
                      <p className="px-3 py-4 text-center text-gray-500 text-xs italic">No themes</p>
                    ) : (
                      themes.map((t) => (
                        <div key={t.name} className="flex items-center justify-between px-3 py-1.5 border-b border-gray-700/50 last:border-0 hover:bg-gray-700/30 group">
                          {renamingTheme?.name === t.name && renamingTheme?.field === field ? (
                            <div className="flex items-center gap-2 flex-1">
                              <input
                                type="text"
                                value={renameValue}
                                onChange={(e) => setRenameValue(e.target.value)}
                                onKeyDown={(e) => { if (e.key === "Enter") handleRenameTheme(); if (e.key === "Escape") setRenamingTheme(null); }}
                                className="bg-gray-700 text-white px-2 py-0.5 rounded border border-indigo-500 text-xs flex-1 focus:outline-none"
                                autoFocus
                              />
                              <button onClick={handleRenameTheme} className="text-green-400 hover:text-green-300 text-xs">Save</button>
                              <button onClick={() => setRenamingTheme(null)} className="text-gray-400 hover:text-gray-300 text-xs">Cancel</button>
                            </div>
                          ) : (
                            <>
                              <button
                                onClick={() => { setRenamingTheme({ name: t.name, field }); setRenameValue(t.name); }}
                                className="text-xs text-gray-200 hover:text-white text-left flex-1"
                                title="Click to rename"
                              >
                                {t.name}
                              </button>
                              <span className="text-[10px] text-gray-500 mr-2">{t.count}</span>
                              <button
                                onClick={() => handleDeleteTheme(t.name, field)}
                                className="text-gray-600 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                                title="Remove theme"
                              >
                                &times;
                              </button>
                            </>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
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
              <h3 className="text-lg font-semibold text-white">Stock Prices</h3>
              <p className="text-sm text-gray-400 mt-1">
                Prices update automatically from Yahoo Finance after market close.
                You can also trigger a manual refresh.
              </p>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                <div className="bg-gray-900/50 rounded-lg p-2.5 border border-gray-700">
                  <span className="text-gray-500">Schedule</span>
                  <p className="text-gray-300 mt-0.5">{schedule || "Daily at 5:30 PM ET"}</p>
                </div>
                <div className="bg-gray-900/50 rounded-lg p-2.5 border border-gray-700">
                  <span className="text-gray-500">Last updated</span>
                  <p className={`mt-0.5 ${lastRefresh ? "text-gray-300" : "text-amber-400"}`}>
                    {formatTimestamp(lastRefresh)}
                  </p>
                </div>
                <div className="bg-gray-900/50 rounded-lg p-2.5 border border-gray-700">
                  <span className="text-gray-500">Next auto-refresh</span>
                  <p className="text-gray-300 mt-0.5">
                    {nextScheduled ? formatTimestamp(nextScheduled) : "Pending"}
                  </p>
                </div>
              </div>
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
                "Manual Refresh"
              )}
            </button>
          </div>

          {refreshResult && (
            <div className="mt-4 p-4 bg-gray-900/50 rounded-lg border border-gray-700">
              <p className="text-sm text-green-400 font-medium">{refreshResult.message}</p>
              {refreshResult.failed.length > 0 && (
                <div className="mt-3">
                  <p className="text-xs text-red-400 font-medium mb-2">
                    {refreshResult.failed.length} tickers failed &mdash; these may be delisted, acquired, or have changed tickers:
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {refreshResult.failed.map((ticker) => (
                      <span
                        key={ticker}
                        className="inline-flex items-center gap-1.5 px-2 py-1 text-xs bg-red-900/30 text-red-300 border border-red-700/50 rounded"
                      >
                        {ticker}
                        <button
                          onClick={async () => {
                            if (!confirm(`Remove "${ticker}" from asset list?\n\nTrade history will be preserved for tax purposes.`)) return;
                            try {
                              const res = await fetch(`/api/assets/${ticker}`, { method: "DELETE" });
                              if (res.ok) {
                                setRefreshResult({
                                  ...refreshResult,
                                  failed: refreshResult.failed.filter((t) => t !== ticker),
                                });
                              }
                            } catch {}
                          }}
                          className="text-red-400 hover:text-white text-xs font-bold ml-0.5"
                          title={`Remove ${ticker} from asset list`}
                        >
                          &times;
                        </button>
                      </span>
                    ))}
                  </div>
                  <button
                    onClick={async () => {
                      if (!confirm(`Remove all ${refreshResult.failed.length} failed tickers from asset list?\n\nTrade history will be preserved.`)) return;
                      for (const ticker of refreshResult.failed) {
                        try { await fetch(`/api/assets/${ticker}`, { method: "DELETE" }); } catch {}
                      }
                      setRefreshResult({ ...refreshResult, failed: [] });
                    }}
                    className="mt-3 px-3 py-1.5 text-xs bg-red-900/40 hover:bg-red-900/60 text-red-300 border border-red-700/50 rounded transition-colors"
                  >
                    Remove all failed tickers
                  </button>
                </div>
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
