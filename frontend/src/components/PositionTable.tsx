import { PortfolioSnapshot } from "../app/types";
import { useState, useMemo } from 'react';

interface PositionTableProps {
    positions: PortfolioSnapshot[];
}

const PositionTable: React.FC<PositionTableProps> = ({ positions }) => {
    const [filterText, setFilterText] = useState("");
    const [sortKey, setSortKey] = useState<keyof PortfolioSnapshot | null>(null);
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

    const handleSort = (key: keyof PortfolioSnapshot) => {
        if (sortKey === key) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        } else {
            setSortKey(key);
            setSortOrder('desc'); // Default to desc for numbers usually
        }
    };

    const sortedAndFilteredPositions = useMemo(() => {
        let data = positions.filter(p => p.ticker.toLowerCase().includes(filterText.toLowerCase()));

        if (sortKey) {
            data.sort((a, b) => {
                const valA = a[sortKey] as string | number;
                const valB = b[sortKey] as string | number;
                if (valA < valB) return sortOrder === 'asc' ? -1 : 1;
                if (valA > valB) return sortOrder === 'asc' ? 1 : -1;
                return 0;
            });
        }
        return data;
    }, [positions, filterText, sortKey, sortOrder]);

    const SortIcon = ({ colKey }: { colKey: keyof PortfolioSnapshot }) => {
        if (sortKey !== colKey) return <span className="text-gray-600 ml-1">⇅</span>;
        return <span className="ml-1 text-white">{sortOrder === 'asc' ? '↑' : '↓'}</span>;
    };

    return (
        <div className="flex flex-col gap-4">
            {/* Filter Input */}
            <input
                type="text"
                placeholder="Filter by Ticker..."
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                className="self-start bg-gray-700 text-white px-4 py-2 rounded-lg border border-gray-600 focus:outline-none focus:border-blue-500 w-full md:w-64"
            />

            <div className="overflow-x-auto rounded-xl border border-gray-700 bg-gray-800 shadow-xl">
                <table className="min-w-full text-left text-sm whitespace-nowrap">
                    <thead className="bg-gray-900/50 uppercase tracking-wider border-b border-gray-700 text-gray-400">
                        <tr>
                            <th scope="col" className="px-6 py-4 font-semibold cursor-pointer hover:text-white" onClick={() => handleSort('ticker')}>Ticker <SortIcon colKey="ticker" /></th>
                            <th scope="col" className="px-6 py-4 font-semibold text-right cursor-pointer hover:text-white" onClick={() => handleSort('quantity')}>Qty <SortIcon colKey="quantity" /></th>
                            <th scope="col" className="px-6 py-4 font-semibold text-right cursor-pointer hover:text-white" onClick={() => handleSort('average_price')}>Avg Price <SortIcon colKey="average_price" /></th>
                            <th scope="col" className="px-6 py-4 font-semibold text-right cursor-pointer hover:text-white" onClick={() => handleSort('current_price')}>Current Price <SortIcon colKey="current_price" /></th>
                            <th scope="col" className="px-6 py-4 font-semibold text-right cursor-pointer hover:text-white" onClick={() => handleSort('market_value')}>Market Value <SortIcon colKey="market_value" /></th>
                            <th scope="col" className="px-6 py-4 font-semibold text-right cursor-pointer hover:text-white" onClick={() => handleSort('unrealized_pnl')}>Unrealized P&L <SortIcon colKey="unrealized_pnl" /></th>
                            <th scope="col" className="px-6 py-4 font-semibold text-right cursor-pointer hover:text-white" onClick={() => handleSort('realized_pnl')}>Realized P&L <SortIcon colKey="realized_pnl" /></th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                        {sortedAndFilteredPositions.map((pos) => (
                            <tr key={pos.ticker} className="hover:bg-gray-700/50 transition-colors">
                                <td className="px-6 py-4 font-medium text-white">{pos.ticker}</td>
                                <td className="px-6 py-4 text-right text-gray-300">{pos.quantity.toLocaleString()}</td>
                                <td className="px-6 py-4 text-right text-gray-300">${pos.average_price.toFixed(2)}</td>
                                <td className="px-6 py-4 text-right text-gray-300">${pos.current_price.toFixed(2)}</td>
                                <td className="px-6 py-4 text-right text-white font-medium">${pos.market_value.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                                <td className={`px-6 py-4 text-right font-medium ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    ${pos.unrealized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                </td>
                                <td className={`px-6 py-4 text-right font-medium ${pos.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    ${pos.realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                                </td>
                            </tr>
                        ))}
                        {sortedAndFilteredPositions.length === 0 && (
                            <tr>
                                <td colSpan={7} className="px-6 py-8 text-center text-gray-500 italic">
                                    No positions found.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default PositionTable;
