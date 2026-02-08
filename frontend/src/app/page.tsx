"use client";

import { useEffect, useState } from 'react';
import PositionTable from '../components/PositionTable';
import ImportButton from '../components/ImportButton';
import ManualTradeForm from '../components/ManualTradeForm';
import { PortfolioSnapshot } from './types';

export default function Home() {
  const [positions, setPositions] = useState<PortfolioSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [showManualTrade, setShowManualTrade] = useState(false);

  const fetchPortfolio = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/portfolio');
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

  const totalPnL = positions.reduce((acc, pos) => acc + pos.realized_pnl + pos.unrealized_pnl, 0);
  const totalMarketValue = positions.reduce((acc, pos) => acc + pos.market_value, 0);

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-8">

        {/* Header */}
        <div className="flex justify-between items-center border-b border-gray-800 pb-6">
          <div>
            <h1 className="text-4xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400">
              Portfolio Tracker
            </h1>
            <p className="mt-2 text-gray-400">Real-time positions and P&L analysis</p>
          </div>
          <div className="flex gap-4">
            <button
              onClick={() => setShowManualTrade(!showManualTrade)}
              className="px-4 py-2 border border-gray-600 rounded-md hover:bg-gray-800 text-gray-300 transition-colors"
            >
              {showManualTrade ? 'Hide Form' : 'Add Trade'}
            </button>
            <ImportButton onImportSuccess={fetchPortfolio} />
          </div>
        </div>

        {/* Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-widest">Net Liquidity</h3>
            <p className="mt-2 text-3xl font-bold text-white">${totalMarketValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}</p>
          </div>
          <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-widest">Total P&L</h3>
            <p className={`mt-2 text-3xl font-bold ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${totalPnL.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </p>
          </div>
          <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
            <h3 className="text-sm font-medium text-gray-400 uppercase tracking-widest">Day Change</h3>
            <p className="mt-2 text-3xl font-bold text-gray-500">
              --
              {/* Placeholder for Day Change */}
            </p>
          </div>
        </div>

        {/* Manual Trade Form */}
        {showManualTrade && (
          <ManualTradeForm onTradeAdded={fetchPortfolio} />
        )}

        {/* Main Content */}
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h2 className="text-xl font-semibold text-gray-200">Current Positions</h2>
            <span className="text-sm text-gray-400">{positions.length} Positions</span>
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
