"use client";

import { useEffect, useState } from "react";
import PositionTable from "../../components/PositionTable";
import { PortfolioSnapshot } from "../types";

export default function PositionsPage() {
  const [positions, setPositions] = useState<PortfolioSnapshot[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/portfolio")
      .then((r) => r.json())
      .then((data) => setPositions(data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const activeCount = positions.filter((p) => p.quantity > 0).length;

  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Positions</h1>
          <p className="mt-1 text-sm text-gray-400">
            All portfolio positions &mdash; {activeCount} active
          </p>
        </div>

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-500" />
          </div>
        ) : (
          <PositionTable positions={positions} />
        )}
      </div>
    </main>
  );
}
