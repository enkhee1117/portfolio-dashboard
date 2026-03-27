"use client";
import { useMemo } from 'react';
import { PortfolioSnapshot } from '../app/types';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';

interface ThemeAnalysisProps {
    positions: PortfolioSnapshot[];
}

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884d8', '#82ca9d', '#ffc658', '#8dd1e1', '#a4de6c', '#d0ed57'];

const ThemeAnalysis: React.FC<ThemeAnalysisProps> = ({ positions }) => {

    const themeData = useMemo(() => {
        const themes: Record<string, number> = {};
        let totalValue = 0;

        positions.forEach(pos => {
            if (pos.quantity > 0 && pos.market_value > 0) { // Only long positions
                const theme = pos.primary_theme || "Unknown";
                themes[theme] = (themes[theme] || 0) + pos.market_value;
                totalValue += pos.market_value;
            }
        });

        return Object.entries(themes)
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value); // Sort by highest exposure
    }, [positions]);

    // Secondary Theme Handling (Optional: could be a second chart or drilldown)

    if (themeData.length === 0) return null;

    return (
        <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">
            <h3 className="text-xl font-semibold text-gray-200 mb-6">Theme Exposure (Primary)</h3>
            <div className="h-[300px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                        <Pie
                            data={themeData}
                            cx="50%"
                            cy="50%"
                            labelLine={false}
                            outerRadius={100}
                            fill="#8884d8"
                            dataKey="value"
                            label={({ name, percent }: any) => `${name} ${(percent * 100).toFixed(0)}%`}
                        >
                            {themeData.map((entry, index) => (
                                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                            ))}
                        </Pie>
                        <Tooltip
                            formatter={(value: any) => [`$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2 })}`, 'Market Value']}
                            contentStyle={{ backgroundColor: '#1f2937', borderColor: '#374151', color: '#f3f4f6' }}
                        />
                        <Legend />
                    </PieChart>
                </ResponsiveContainer>
            </div>

            {/* Table Breakdown */}
            <div className="mt-8 overflow-x-auto">
                <table className="min-w-full text-left text-sm whitespace-nowrap">
                    <thead className="bg-gray-700/50 uppercase tracking-wider border-b border-gray-600 text-gray-400">
                        <tr>
                            <th className="px-4 py-2">Theme</th>
                            <th className="px-4 py-2 text-right">Exposure</th>
                            <th className="px-4 py-2 text-right">% Portfolio</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                        {themeData.map((item) => {
                            const total = themeData.reduce((acc, curr) => acc + curr.value, 0);
                            const percent = (item.value / total) * 100;
                            return (
                                <tr key={item.name} className="hover:bg-gray-700/25">
                                    <td className="px-4 py-2 font-medium text-gray-200">{item.name}</td>
                                    <td className="px-4 py-2 text-right text-gray-300">${item.value.toLocaleString(undefined, { minimumFractionDigits: 0 })}</td>
                                    <td className="px-4 py-2 text-right text-gray-400">{percent.toFixed(1)}%</td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default ThemeAnalysis;
