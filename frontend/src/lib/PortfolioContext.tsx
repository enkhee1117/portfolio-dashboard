"use client";
import { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import { useAuth } from "./AuthContext";
import { apiCall } from "./api";
import { PortfolioSnapshot, Asset, Trade } from "../app/types";

interface PortfolioContextValue {
  positions: PortfolioSnapshot[];
  assets: Asset[];
  recentTrades: Trade[];
  loading: boolean;
  refresh: () => Promise<void>;
  // Derived
  activePositions: PortfolioSnapshot[];
  themes: { primary: string[]; secondary: string[] };
}

const PortfolioContext = createContext<PortfolioContextValue | null>(null);

export function PortfolioProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [positions, setPositions] = useState<PortfolioSnapshot[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    if (!user) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [posRes, assetRes, tradeRes] = await Promise.all([
        apiCall("/api/portfolio"),
        apiCall("/api/assets"),
        apiCall("/api/trades?limit=5"),
      ]);
      if (posRes.ok) setPositions(await posRes.json());
      if (assetRes.ok) {
        setAssets(await assetRes.json());
      }
      if (tradeRes.ok) setRecentTrades(await tradeRes.json());
    } catch (err) {
      console.error("Portfolio fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const activePositions = useMemo(
    () => positions.filter(p => p.quantity > 0),
    [positions]
  );

  const themes = useMemo(() => {
    const primary = new Set<string>();
    const secondary = new Set<string>();
    assets.forEach(a => {
      if (a.primary_theme) primary.add(a.primary_theme);
      if (a.secondary_theme) secondary.add(a.secondary_theme);
    });
    return { primary: [...primary].sort(), secondary: [...secondary].sort() };
  }, [assets]);

  const value = useMemo(() => ({
    positions, assets, recentTrades, loading,
    refresh: fetchAll, activePositions, themes,
  }), [positions, assets, recentTrades, loading, fetchAll, activePositions, themes]);

  return (
    <PortfolioContext.Provider value={value}>
      {children}
    </PortfolioContext.Provider>
  );
}

export function usePortfolio() {
  const ctx = useContext(PortfolioContext);
  if (!ctx) throw new Error("usePortfolio must be used inside PortfolioProvider");
  return ctx;
}
