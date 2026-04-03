import { useState, useEffect } from "react";
import { apiCall } from "./api";

const defaultFlags: Record<string, boolean> = {
  wash_sales: true,
  rsi_screener: true,
  theme_baskets: true,
  intraday_refresh: true,
  recent_trades: true,
  daily_movers: true,
};

let cachedFlags: Record<string, boolean> | null = null;

export function useFeatureFlags() {
  const [flags, setFlags] = useState<Record<string, boolean>>(cachedFlags || defaultFlags);

  useEffect(() => {
    if (cachedFlags) return;
    apiCall("/api/config")
      .then(async (r) => {
        if (r.ok) {
          const data = await r.json();
          cachedFlags = data.features;
          setFlags(data.features);
        }
      })
      .catch(() => {}); // Fall back to defaults silently
  }, []);

  return flags;
}
