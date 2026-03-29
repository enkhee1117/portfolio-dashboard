"use client";

import { useEffect, useState, useMemo } from "react";
import { Asset, ThemeLists } from "../types";

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [themes, setThemes] = useState<ThemeLists>({ primary: [], secondary: [] });
  const [loading, setLoading] = useState(true);

  // Filter & sort
  const [filterText, setFilterText] = useState("");
  const [themeFilter, setThemeFilter] = useState("");
  const [sortKey, setSortKey] = useState<string>("ticker");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  // Add form
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({ ticker: "", primary_theme: "", secondary_theme: "", price: "" });
  const [addLoading, setAddLoading] = useState(false);

  // Edit modal
  const [editing, setEditing] = useState<Asset | null>(null);
  const [editForm, setEditForm] = useState({ primary_theme: "", secondary_theme: "", price: "" });

  const fetchAssets = async () => {
    try {
      const [assetsRes, themesRes] = await Promise.all([
        fetch("/api/assets"),
        fetch("/api/assets/themes"),
      ]);
      if (assetsRes.ok) setAssets(await assetsRes.json());
      if (themesRes.ok) setThemes(await themesRes.json());
    } catch (err) {
      console.error("Failed to fetch assets", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAssets(); }, []);

  // All unique themes for the dropdown filter
  const allThemes = useMemo(() => {
    const set = new Set<string>();
    assets.forEach((a) => {
      if (a.primary_theme) set.add(a.primary_theme);
      if (a.secondary_theme) set.add(a.secondary_theme);
    });
    return Array.from(set).sort();
  }, [assets]);

  // Sort & filter
  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortOrder(key === "ticker" || key === "primary_theme" ? "asc" : "desc");
    }
  };

  const filtered = useMemo(() => {
    const q = filterText.toLowerCase();
    let data = assets.filter((a) => {
      // Text filter
      const matchesText =
        !q ||
        a.ticker.toLowerCase().includes(q) ||
        a.primary_theme.toLowerCase().includes(q) ||
        a.secondary_theme.toLowerCase().includes(q);
      // Theme dropdown filter
      const matchesTheme =
        !themeFilter ||
        a.primary_theme === themeFilter ||
        a.secondary_theme === themeFilter;
      return matchesText && matchesTheme;
    });
    data.sort((a, b) => {
      const vA = (a as any)[sortKey] ?? "";
      const vB = (b as any)[sortKey] ?? "";
      if (vA < vB) return sortOrder === "asc" ? -1 : 1;
      if (vA > vB) return sortOrder === "asc" ? 1 : -1;
      return 0;
    });
    return data;
  }, [assets, filterText, themeFilter, sortKey, sortOrder]);

  const SortIcon = ({ colKey }: { colKey: string }) => {
    if (sortKey !== colKey) return <span className="text-gray-600 ml-1">&#8693;</span>;
    return <span className="ml-1 text-white">{sortOrder === "asc" ? "\u2191" : "\u2193"}</span>;
  };

  // Add asset
  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddLoading(true);
    try {
      const res = await fetch("/api/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker: addForm.ticker.toUpperCase(),
          primary_theme: addForm.primary_theme,
          secondary_theme: addForm.secondary_theme,
          price: parseFloat(addForm.price) || 0,
        }),
      });
      if (res.status === 409) {
        alert("This ticker already exists.");
      } else if (res.ok) {
        setAddForm({ ticker: "", primary_theme: "", secondary_theme: "", price: "" });
        setShowAdd(false);
        fetchAssets();
      } else {
        alert("Failed to add asset.");
      }
    } catch {
      alert("Error adding asset.");
    } finally {
      setAddLoading(false);
    }
  };

  // Edit asset
  const openEdit = (asset: Asset) => {
    setEditing(asset);
    setEditForm({
      primary_theme: asset.primary_theme,
      secondary_theme: asset.secondary_theme,
      price: String(asset.price),
    });
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    try {
      const res = await fetch(`/api/assets/${editing.ticker}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          primary_theme: editForm.primary_theme,
          secondary_theme: editForm.secondary_theme,
          price: parseFloat(editForm.price) || 0,
        }),
      });
      if (res.ok) {
        setEditing(null);
        fetchAssets();
      } else {
        alert("Failed to update asset.");
      }
    } catch {
      alert("Error updating asset.");
    }
  };

  // Delete asset
  const handleDelete = async (ticker: string) => {
    if (!confirm(`Delete asset "${ticker}"? This removes its theme data.`)) return;
    try {
      const res = await fetch(`/api/assets/${ticker}`, { method: "DELETE" });
      if (res.ok) {
        setAssets(assets.filter((a) => a.ticker !== ticker));
      } else {
        alert("Failed to delete asset.");
      }
    } catch {
      alert("Error deleting asset.");
    }
  };

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Page Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-2xl font-bold text-white">Asset Registry</h1>
            <p className="mt-1 text-sm text-gray-400">
              Manage stock themes and metadata &mdash; {assets.length} assets registered
              {themeFilter && (
                <span className="ml-2 text-indigo-400">
                  (filtered: {themeFilter})
                </span>
              )}
            </p>
          </div>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-md transition-colors"
          >
            {showAdd ? "Cancel" : "+ Add Asset"}
          </button>
        </div>

        {/* Add Form */}
        {showAdd && (
          <form
            onSubmit={handleAdd}
            className="bg-gray-800 rounded-xl p-6 border border-gray-700 shadow-lg"
          >
            <h3 className="text-lg font-semibold text-white mb-4">Register New Asset</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Ticker</label>
                <input
                  type="text"
                  value={addForm.ticker}
                  onChange={(e) => setAddForm({ ...addForm, ticker: e.target.value })}
                  placeholder="AAPL"
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none uppercase"
                  required
                />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Primary Theme</label>
                <input
                  type="text"
                  list="primary-themes"
                  value={addForm.primary_theme}
                  onChange={(e) => setAddForm({ ...addForm, primary_theme: e.target.value })}
                  placeholder="e.g. AI, Energy"
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
                  required
                />
                <datalist id="primary-themes">
                  {themes.primary.map((t) => <option key={t} value={t} />)}
                </datalist>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Secondary Theme</label>
                <input
                  type="text"
                  list="secondary-themes"
                  value={addForm.secondary_theme}
                  onChange={(e) => setAddForm({ ...addForm, secondary_theme: e.target.value })}
                  placeholder="e.g. Semiconductor"
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
                  required
                />
                <datalist id="secondary-themes">
                  {themes.secondary.map((t) => <option key={t} value={t} />)}
                </datalist>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Price</label>
                <input
                  type="number"
                  step="0.01"
                  value={addForm.price}
                  onChange={(e) => setAddForm({ ...addForm, price: e.target.value })}
                  placeholder="0.00"
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
                />
              </div>
            </div>
            <button
              type="submit"
              disabled={addLoading}
              className="mt-4 px-6 py-2 bg-green-600 hover:bg-green-700 text-white rounded-md text-sm font-medium transition-colors disabled:opacity-50"
            >
              {addLoading ? "Adding..." : "Register Asset"}
            </button>
          </form>
        )}

        {/* Filters */}
        <div className="flex items-center gap-3 flex-wrap">
          <input
            type="text"
            placeholder="Search by ticker or theme..."
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            className="bg-gray-800 text-white px-4 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 w-full md:w-72 text-sm"
          />
          <select
            value={themeFilter}
            onChange={(e) => setThemeFilter(e.target.value)}
            className="bg-gray-800 text-white px-4 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 text-sm"
          >
            <option value="">All Themes</option>
            {allThemes.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          {themeFilter && (
            <button
              onClick={() => setThemeFilter("")}
              className="text-xs text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700"
            >
              Clear filter
            </button>
          )}
          <span className="text-xs text-gray-500 ml-auto">
            {filtered.length} of {assets.length} shown
          </span>
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500" />
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-gray-700 bg-gray-800 shadow-xl">
            <table className="min-w-full text-left text-sm whitespace-nowrap">
              <thead className="bg-gray-900/50 uppercase tracking-wider border-b border-gray-700 text-gray-400">
                <tr>
                  <th className="px-4 py-3 cursor-pointer hover:text-white text-xs" onClick={() => handleSort("ticker")}>
                    Ticker <SortIcon colKey="ticker" />
                  </th>
                  <th className="px-4 py-3 cursor-pointer hover:text-white text-xs" onClick={() => handleSort("primary_theme")}>
                    Primary <SortIcon colKey="primary_theme" />
                  </th>
                  <th className="px-4 py-3 cursor-pointer hover:text-white text-xs" onClick={() => handleSort("secondary_theme")}>
                    Secondary <SortIcon colKey="secondary_theme" />
                  </th>
                  <th className="px-4 py-3 text-right cursor-pointer hover:text-white text-xs" onClick={() => handleSort("price")}>
                    Price <SortIcon colKey="price" />
                  </th>
                  <th className="px-4 py-3 text-right cursor-pointer hover:text-white text-xs" onClick={() => handleSort("daily_change_pct")}>
                    Daily Chg <SortIcon colKey="daily_change_pct" />
                  </th>
                  <th className="px-4 py-3 text-right text-xs">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {filtered.map((asset) => (
                  <tr key={asset.ticker} className="hover:bg-gray-700/50 transition-colors">
                    <td className="px-4 py-2.5 font-medium text-white">{asset.ticker}</td>
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => setThemeFilter(asset.primary_theme)}
                        className="px-2 py-0.5 rounded-full text-xs font-medium bg-indigo-900/40 text-indigo-300 border border-indigo-700/50 hover:bg-indigo-900/60 transition-colors"
                      >
                        {asset.primary_theme}
                      </button>
                    </td>
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => setThemeFilter(asset.secondary_theme)}
                        className="px-2 py-0.5 rounded-full text-xs font-medium bg-cyan-900/40 text-cyan-300 border border-cyan-700/50 hover:bg-cyan-900/60 transition-colors"
                      >
                        {asset.secondary_theme}
                      </button>
                    </td>
                    <td className="px-4 py-2.5 text-right text-gray-300">
                      ${asset.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {asset.daily_change_pct != null ? (
                        <span className={`font-medium ${asset.daily_change_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                          {asset.daily_change_pct >= 0 ? "+" : ""}{asset.daily_change_pct.toFixed(2)}%
                          <span className="text-xs ml-1 text-gray-500">
                            ({asset.daily_change_pct >= 0 ? "+" : ""}${asset.daily_change?.toFixed(2)})
                          </span>
                        </span>
                      ) : (
                        <span className="text-gray-600 text-xs">--</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right space-x-2">
                      <button onClick={() => openEdit(asset)} className="text-blue-400 hover:text-blue-300 text-xs">
                        Edit
                      </button>
                      <button onClick={() => handleDelete(asset.ticker)} className="text-red-400 hover:text-red-300 text-xs">
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-gray-500 italic">
                      No assets found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Edit Modal */}
      {editing && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50"
          onClick={(e) => { if (e.target === e.currentTarget) setEditing(null); }}
        >
          <div className="bg-gray-800 rounded-xl shadow-xl border border-gray-700 w-full max-w-md p-6">
            <h2 className="text-xl font-bold text-white mb-1">Edit {editing.ticker}</h2>
            <p className="text-sm text-gray-400 mb-4">Update theme assignments and price</p>
            <form onSubmit={handleUpdate} className="space-y-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Primary Theme</label>
                <input
                  type="text"
                  list="edit-primary-themes"
                  value={editForm.primary_theme}
                  onChange={(e) => setEditForm({ ...editForm, primary_theme: e.target.value })}
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
                  required
                />
                <datalist id="edit-primary-themes">
                  {themes.primary.map((t) => <option key={t} value={t} />)}
                </datalist>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Secondary Theme</label>
                <input
                  type="text"
                  list="edit-secondary-themes"
                  value={editForm.secondary_theme}
                  onChange={(e) => setEditForm({ ...editForm, secondary_theme: e.target.value })}
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
                  required
                />
                <datalist id="edit-secondary-themes">
                  {themes.secondary.map((t) => <option key={t} value={t} />)}
                </datalist>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Price</label>
                <input
                  type="number"
                  step="0.01"
                  value={editForm.price}
                  onChange={(e) => setEditForm({ ...editForm, price: e.target.value })}
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
                />
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setEditing(null)}
                  className="px-4 py-2 hover:bg-gray-700 rounded text-gray-300 text-sm"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-white text-sm"
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
