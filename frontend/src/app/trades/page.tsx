"use client";

import { useEffect, useState, useMemo } from 'react';
import { Trade } from '../types';
import { useToast } from '../../components/Toast';

export default function TradeHistory() {
    const [trades, setTrades] = useState<Trade[]>([]);
    const [loading, setLoading] = useState(true);
    const toast = useToast();
    const [filterText, setFilterText] = useState("");
    const [dateFrom, setDateFrom] = useState("");
    const [dateTo, setDateTo] = useState("");

    // Sorting state
    const [sortKey, setSortKey] = useState<keyof Trade | null>('date');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

    useEffect(() => {
        fetch('/api/trades')
            .then(res => res.json())
            .then(data => {
                setTrades(data);
                setLoading(false);
            })
            .catch(err => {
                console.error("Failed to fetch trades", err);
                setLoading(false);
            });
    }, []);

    const handleSort = (key: keyof Trade) => {
        if (sortKey === key) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        } else {
            setSortKey(key);
            setSortOrder('desc'); // Newer dates first usually
        }
    };

    const sortedAndFilteredTrades = useMemo(() => {
        const q = filterText.toLowerCase();
        let data = trades.filter(t => {
            const matchesText = !q || t.ticker.toLowerCase().includes(q) || t.type.toLowerCase().includes(q);
            const tradeDate = t.date.slice(0, 10); // YYYY-MM-DD
            const matchesFrom = !dateFrom || tradeDate >= dateFrom;
            const matchesTo = !dateTo || tradeDate <= dateTo;
            return matchesText && matchesFrom && matchesTo;
        });

        if (sortKey) {
            data.sort((a, b) => {
                const valA = a[sortKey] ?? "";
                const valB = b[sortKey] ?? "";

                if (valA < valB) return sortOrder === 'asc' ? -1 : 1;
                if (valA > valB) return sortOrder === 'asc' ? 1 : -1;
                return 0;
            });
        }
        return data;
    }, [trades, filterText, dateFrom, dateTo, sortKey, sortOrder]);

    const SortIcon = ({ colKey }: { colKey: keyof Trade }) => {
        if (sortKey !== colKey) return <span className="text-gray-600 ml-1">⇅</span>;
        return <span className="ml-1 text-white">{sortOrder === 'asc' ? '↑' : '↓'}</span>;
    };

    const [editingTrade, setEditingTrade] = useState<Trade | null>(null);

    // Handlers
    const handleDelete = async (id: string) => {
        if (!confirm("Are you sure you want to delete this trade?")) return;

        try {
            const res = await fetch(`/api/trades/${id}`, { method: 'DELETE' });
            if (res.ok) {
                setTrades(trades.filter(t => t.id !== id));
            } else {
                toast.error("Failed to delete trade");
            }
        } catch (err) {
            console.error(err);
            toast.error("Error deleting trade");
        }
    };

    const handleEditClick = (trade: Trade) => {
        setEditingTrade(trade);
    };

    const handleUpdate = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editingTrade) return;

        try {
            const res = await fetch(`/api/trades/${editingTrade.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...editingTrade,
                    date: editingTrade.date, // Ensure format is correct if edited
                    // price/qty needs to be numbers
                    price: Number(editingTrade.price),
                    quantity: Number(editingTrade.quantity)
                })
            });

            if (res.ok) {
                const updatedTrade = await res.json();
                setTrades(trades.map(t => t.id === updatedTrade.id ? updatedTrade : t));
                setEditingTrade(null);
            } else {
                toast.error("Failed to update trade");
            }
        } catch (err) {
            console.error(err);
            toast.error("Error updating trade");
        }
    };

    return (
        <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
            <div className="max-w-7xl mx-auto space-y-8">
                {/* Page Header */}
                <div>
                    <h1 className="text-2xl font-bold text-white">Trade History</h1>
                    <p className="mt-1 text-sm text-gray-400">View and manage all past transactions</p>
                </div>

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
                    <input
                        type="date"
                        value={dateFrom}
                        onChange={(e) => setDateFrom(e.target.value)}
                        className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 text-sm [&::-webkit-calendar-picker-indicator]:invert"
                    />
                    <span>To</span>
                    <input
                        type="date"
                        value={dateTo}
                        onChange={(e) => setDateTo(e.target.value)}
                        className="bg-gray-800 text-white px-3 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-indigo-500 text-sm [&::-webkit-calendar-picker-indicator]:invert"
                    />
                    {(dateFrom || dateTo) && (
                        <button
                            onClick={() => { setDateFrom(""); setDateTo(""); }}
                            className="text-gray-400 hover:text-white px-2 py-1 rounded hover:bg-gray-700"
                        >
                            Clear dates
                        </button>
                    )}
                </div>
                <span className="text-xs text-gray-500 ml-auto">
                    {sortedAndFilteredTrades.length} of {trades.length} trades
                </span>
                </div>

                {/* Table */}
                <div className="overflow-x-auto rounded-xl border border-gray-700 bg-gray-800 shadow-xl">
                    <table className="min-w-full text-left text-sm whitespace-nowrap">
                        <thead className="bg-gray-900/50 uppercase tracking-wider border-b border-gray-700 text-gray-400">
                            <tr>
                                <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('date')}>Date <SortIcon colKey="date" /></th>
                                <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('ticker')}>Ticker <SortIcon colKey="ticker" /></th>
                                <th className="px-6 py-4 cursor-pointer hover:text-white" onClick={() => handleSort('side')}>Side <SortIcon colKey="side" /></th>
                                <th className="px-6 py-4 text-right cursor-pointer hover:text-white" onClick={() => handleSort('quantity')}>Qty <SortIcon colKey="quantity" /></th>
                                <th className="px-6 py-4 text-right cursor-pointer hover:text-white" onClick={() => handleSort('price')}>Price <SortIcon colKey="price" /></th>
                                <th className="px-6 py-4 text-right">Total</th>
                                <th className="px-6 py-4 text-center">Status</th>
                                <th className="px-6 py-4 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-700">
                            {sortedAndFilteredTrades.map((trade) => (
                                <tr key={trade.id} className={`hover:bg-gray-700/50 transition-colors ${trade.is_wash_sale ? 'bg-red-900/10' : ''}`}>
                                    <td className="px-6 py-4 text-gray-300">{new Date(trade.date).toLocaleDateString()}</td>
                                    <td className="px-6 py-4 font-medium text-white">{trade.ticker}</td>
                                    <td className={`px-6 py-4 font-semibold ${trade.side === 'Buy' ? 'text-green-400' : 'text-red-400'}`}>
                                        {trade.side}
                                    </td>
                                    <td className="px-6 py-4 text-right text-gray-300">{trade.quantity.toLocaleString()}</td>
                                    <td className="px-6 py-4 text-right text-gray-300">${trade.price.toFixed(2)}</td>
                                    <td className="px-6 py-4 text-right text-white font-medium">
                                        ${(trade.quantity * trade.price).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                    </td>
                                    <td className="px-6 py-4 text-center">
                                        {trade.is_wash_sale && (
                                            <span
                                                className="px-2 py-1 text-xs font-bold text-red-100 bg-red-600 rounded-full cursor-help"
                                                title="IRS Wash Sale: You sold at a loss and repurchased within 30 days. The loss is disallowed for tax purposes and added to the cost basis of the replacement shares."
                                            >
                                                WASH SALE
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-6 py-4 text-right space-x-2">
                                        <button onClick={() => handleEditClick(trade)} className="text-blue-400 hover:text-blue-300">
                                            Edit
                                        </button>
                                        <button onClick={() => handleDelete(trade.id)} className="text-red-400 hover:text-red-300">
                                            Delete
                                        </button>
                                    </td>
                                </tr>
                            ))}
                            {sortedAndFilteredTrades.length === 0 && !loading && (
                                <tr>
                                    <td colSpan={8} className="px-6 py-8 text-center text-gray-500 italic">
                                        No trades found. Import your trade history from <a href="/settings" className="text-indigo-400 hover:underline">Settings</a> or add trades from the <a href="/" className="text-indigo-400 hover:underline">Dashboard</a>.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Edit Modal */}
            {editingTrade && (
                <div className="fixed inset-0 bg-black/70 flex items-center justify-center p-4 z-50">
                    <div className="bg-gray-800 rounded-lg shadow-xl border border-gray-700 w-full max-w-lg p-6">
                        <h2 className="text-xl font-bold text-white mb-4">Edit Trade</h2>
                        <form onSubmit={handleUpdate} className="space-y-4">
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Date</label>
                                    <input
                                        type="date"
                                        value={editingTrade.date ? new Date(editingTrade.date).toISOString().slice(0, 10) : ''}
                                        onChange={e => {
                                            // Store as ISO string (with default time) to be consistent with API/Type
                                            // e.target.value is YYYY-MM-DD
                                            if (e.target.value) {
                                                const dateObj = new Date(e.target.value);
                                                // Set to noon to avoid timezone issues shifting the day
                                                dateObj.setHours(12, 0, 0, 0);
                                                setEditingTrade({ ...editingTrade, date: dateObj.toISOString() });
                                            }
                                        }}
                                        className="w-full bg-gray-700 text-white rounded p-2 [&::-webkit-calendar-picker-indicator]:invert [&::-webkit-calendar-picker-indicator]:cursor-pointer [&::-webkit-calendar-picker-indicator]:w-6 [&::-webkit-calendar-picker-indicator]:h-6"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Ticker</label>
                                    <input
                                        type="text"
                                        value={editingTrade.ticker}
                                        onChange={e => setEditingTrade({ ...editingTrade, ticker: e.target.value })}
                                        className="w-full bg-gray-700 text-white rounded p-2 uppercase"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Side</label>
                                    <select
                                        value={editingTrade.side}
                                        onChange={e => setEditingTrade({ ...editingTrade, side: e.target.value })}
                                        className="w-full bg-gray-700 text-white rounded p-2"
                                    >
                                        <option value="Buy">Buy</option>
                                        <option value="Sell">Sell</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Type</label>
                                    <select
                                        value={editingTrade.type}
                                        onChange={e => setEditingTrade({ ...editingTrade, type: e.target.value })}
                                        className="w-full bg-gray-700 text-white rounded p-2"
                                    >
                                        <option value="Equity">Equity</option>
                                        <option value="Option">Option</option>
                                    </select>
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Quantity</label>
                                    <input
                                        type="number"
                                        step="any"
                                        value={editingTrade.quantity}
                                        onChange={e => setEditingTrade({ ...editingTrade, quantity: parseFloat(e.target.value) || 0 })}
                                        className="w-full bg-gray-700 text-white rounded p-2"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Price</label>
                                    <input
                                        type="number"
                                        step="any"
                                        value={editingTrade.price}
                                        onChange={e => setEditingTrade({ ...editingTrade, price: parseFloat(e.target.value) || 0 })}
                                        className="w-full bg-gray-700 text-white rounded p-2"
                                    />
                                </div>
                            </div>
                            <div className="flex justify-end gap-3 mt-6">
                                <button
                                    type="button"
                                    onClick={() => setEditingTrade(null)}
                                    className="px-4 py-2 hover:bg-gray-700 rounded text-gray-300"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 rounded text-white"
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
