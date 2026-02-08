"use client";

import { useEffect, useState, useMemo } from 'react';
import { Trade } from '../types';
import Link from 'next/link';

export default function TradeHistory() {
    const [trades, setTrades] = useState<Trade[]>([]);
    const [loading, setLoading] = useState(true);
    const [filterText, setFilterText] = useState("");

    // Sorting state
    const [sortKey, setSortKey] = useState<keyof Trade | null>('date');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

    useEffect(() => {
        fetch('http://localhost:8000/trades')
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
        let data = trades.filter(t =>
            t.ticker.toLowerCase().includes(filterText.toLowerCase()) ||
            t.type.toLowerCase().includes(filterText.toLowerCase())
        );

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
    }, [trades, filterText, sortKey, sortOrder]);

    const SortIcon = ({ colKey }: { colKey: keyof Trade }) => {
        if (sortKey !== colKey) return <span className="text-gray-600 ml-1">⇅</span>;
        return <span className="ml-1 text-white">{sortOrder === 'asc' ? '↑' : '↓'}</span>;
    };

    return (
        <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
            <div className="max-w-7xl mx-auto space-y-8">
                {/* Header */}
                <div className="flex justify-between items-center border-b border-gray-800 pb-6">
                    <div>
                        <h1 className="text-3xl font-bold text-white">Trade History</h1>
                        <p className="mt-2 text-gray-400">View all past transactions.</p>
                    </div>
                    <Link href="/" className="px-4 py-2 border border-blue-500 text-blue-400 rounded-md hover:bg-blue-900/20 transition-colors">
                        Back to Dashboard
                    </Link>
                </div>

                {/* Filters */}
                <input
                    type="text"
                    placeholder="Filter by Ticker or Type..."
                    value={filterText}
                    onChange={(e) => setFilterText(e.target.value)}
                    className="bg-gray-800 text-white px-4 py-2 rounded-lg border border-gray-700 focus:outline-none focus:border-blue-500 w-full md:w-64"
                />

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
                                        ${(trade.quantity * trade.price).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                    </td>
                                    <td className="px-6 py-4 text-center">
                                        {trade.is_wash_sale && (
                                            <span className="px-2 py-1 text-xs font-bold text-red-100 bg-red-600 rounded-full">
                                                WASH SALE
                                            </span>
                                        )}
                                    </td>
                                </tr>
                            ))}
                            {sortedAndFilteredTrades.length === 0 && !loading && (
                                <tr>
                                    <td colSpan={7} className="px-6 py-8 text-center text-gray-500 italic">
                                        No trades found.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </main>
    );
}
