"use client";
import { useState, useEffect } from "react";
import { Asset, ThemeLists } from "../app/types";
import { useToast } from "./Toast";
import { apiCall } from "../lib/api";
import { useAuth } from "../lib/AuthContext";

interface ManualTradeFormProps {
  onTradeAdded: () => void;
}

const ManualTradeForm: React.FC<ManualTradeFormProps> = ({ onTradeAdded }) => {
  const [formData, setFormData] = useState({
    date: new Date().toISOString().split("T")[0],
    ticker: "",
    type: "Equity",
    side: "Buy",
    price: "",
    quantity: "",
    fees: "",
    currency: "USD",
  });
  const [loading, setLoading] = useState(false);

  // Asset registration state
  const [assets, setAssets] = useState<Asset[]>([]);
  const [themes, setThemes] = useState<ThemeLists>({ primary: [], secondary: [] });
  const [tickerStatus, setTickerStatus] = useState<"idle" | "registered" | "unregistered">("idle");
  const [showRegister, setShowRegister] = useState(false);
  const [regForm, setRegForm] = useState({ primary_theme: "", secondary_theme: "", price: "" });
  const [regLoading, setRegLoading] = useState(false);
  const { user } = useAuth();
  const toast = useToast();

  // Fetch assets when auth is ready, derive themes client-side
  useEffect(() => {
    if (!user) return;
    apiCall("/api/assets")
      .then(async (r) => {
        if (r.ok) {
          const data = await r.json();
          setAssets(data);
          const primary = new Set<string>();
          const secondary = new Set<string>();
          data.forEach((a: any) => {
            if (a.primary_theme) primary.add(a.primary_theme);
            if (a.secondary_theme) secondary.add(a.secondary_theme);
          });
          setThemes({ primary: [...primary].sort(), secondary: [...secondary].sort() });
        }
      })
      .catch(console.error);
  }, [user]);

  // Check ticker when it changes
  const checkTicker = (ticker: string) => {
    if (!ticker.trim()) {
      setTickerStatus("idle");
      setShowRegister(false);
      return;
    }
    const upper = ticker.toUpperCase();
    const found = assets.some((a) => a.ticker === upper);
    setTickerStatus(found ? "registered" : "unregistered");
    setShowRegister(!found);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData({ ...formData, [name]: value });
    if (name === "ticker") {
      checkTicker(value);
    }
  };

  // Register the new asset inline
  const handleRegister = async () => {
    const ticker = formData.ticker.toUpperCase();
    if (!regForm.primary_theme || !regForm.secondary_theme) {
      toast.error("Both themes are required.");
      return;
    }
    setRegLoading(true);
    try {
      const res = await apiCall("/api/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker,
          primary_theme: regForm.primary_theme,
          secondary_theme: regForm.secondary_theme,
          price: parseFloat(regForm.price) || 0,
        }),
      });
      if (res.ok) {
        const newAsset = await res.json();
        setAssets([...assets, newAsset]);
        setTickerStatus("registered");
        setShowRegister(false);
        setRegForm({ primary_theme: "", secondary_theme: "", price: "" });
      } else if (res.status === 409) {
        // Already exists — mark as registered
        setTickerStatus("registered");
        setShowRegister(false);
      } else {
        toast.error("Failed to register asset.");
      }
    } catch {
      toast.error("Error registering asset.");
    } finally {
      setRegLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (tickerStatus === "unregistered") {
      toast.error("Please register this ticker with themes before adding a trade.");
      return;
    }
    setLoading(true);
    try {
      let res = await apiCall("/api/trades/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...formData,
          price: parseFloat(formData.price),
          quantity: parseFloat(formData.quantity),
          fees: parseFloat(formData.fees) || 0,
        }),
      });

      if (res.status === 409) {
        if (confirm("This looks like a duplicate trade. Add it anyway?")) {
          res = await apiCall("/api/trades/manual?force=true", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ...formData,
              price: parseFloat(formData.price),
              quantity: parseFloat(formData.quantity),
            }),
          });
        } else {
          setLoading(false);
          return;
        }
      }

      if (res.ok) {
        toast.success("Trade added successfully!");
        onTradeAdded();
        setFormData({ ...formData, ticker: "", price: "", quantity: "" });
        setTickerStatus("idle");
      } else {
        toast.error("Failed to add trade.");
      }
    } catch (err) {
      console.error(err);
      toast.error("Error adding trade.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-gray-800 rounded-xl p-6 shadow-lg border border-gray-700">

      <form onSubmit={handleSubmit}>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Date</label>
            <input
              type="date"
              name="date"
              value={formData.date}
              onChange={handleChange}
              className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none [&::-webkit-calendar-picker-indicator]:invert"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Ticker
              {tickerStatus === "registered" && (
                <span className="ml-2 text-green-400 text-xs">Registered</span>
              )}
              {tickerStatus === "unregistered" && (
                <span className="ml-2 text-amber-400 text-xs">Not registered</span>
              )}
            </label>
            <input
              type="text"
              name="ticker"
              placeholder="AAPL"
              value={formData.ticker}
              onChange={handleChange}
              onBlur={() => checkTicker(formData.ticker)}
              className={`w-full bg-gray-700 text-white p-2 rounded border focus:outline-none uppercase ${
                tickerStatus === "registered"
                  ? "border-green-600"
                  : tickerStatus === "unregistered"
                    ? "border-amber-600"
                    : "border-gray-600 focus:border-indigo-500"
              }`}
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Side</label>
            <select
              name="side"
              value={formData.side}
              onChange={handleChange}
              className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
            >
              <option value="Buy">Buy</option>
              <option value="Sell">Sell</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Quantity</label>
            <input
              type="number"
              step="0.01"
              name="quantity"
              placeholder="0"
              value={formData.quantity}
              onChange={handleChange}
              className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Price</label>
            <input
              type="number"
              step="0.01"
              name="price"
              placeholder="0.00"
              value={formData.price}
              onChange={handleChange}
              className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Fees</label>
            <input
              type="number"
              step="0.01"
              name="fees"
              placeholder="0.00"
              value={formData.fees}
              onChange={handleChange}
              className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Inline Registration for unregistered tickers */}
        {showRegister && (
          <div className="mt-4 p-4 bg-amber-900/20 border border-amber-700/50 rounded-lg">
            <p className="text-sm text-amber-300 mb-3">
              <strong>{formData.ticker.toUpperCase()}</strong> is not registered. Assign themes before trading:
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Primary Theme</label>
                <input
                  type="text"
                  list="reg-primary-themes"
                  value={regForm.primary_theme}
                  onChange={(e) => setRegForm({ ...regForm, primary_theme: e.target.value })}
                  placeholder="e.g. AI, Energy"
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none text-sm"
                  required
                />
                <datalist id="reg-primary-themes">
                  {themes.primary.map((t) => (
                    <option key={t} value={t} />
                  ))}
                </datalist>
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Secondary Theme</label>
                <input
                  type="text"
                  list="reg-secondary-themes"
                  value={regForm.secondary_theme}
                  onChange={(e) => setRegForm({ ...regForm, secondary_theme: e.target.value })}
                  placeholder="e.g. Semiconductor"
                  className="w-full bg-gray-700 text-white p-2 rounded border border-gray-600 focus:border-indigo-500 focus:outline-none text-sm"
                  required
                />
                <datalist id="reg-secondary-themes">
                  {themes.secondary.map((t) => (
                    <option key={t} value={t} />
                  ))}
                </datalist>
              </div>
              <div className="flex items-end">
                <button
                  type="button"
                  onClick={handleRegister}
                  disabled={regLoading}
                  className="w-full px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded text-sm font-medium transition-colors disabled:opacity-50"
                >
                  {regLoading ? "Registering..." : "Register Asset"}
                </button>
              </div>
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={loading || tickerStatus === "unregistered"}
          className="mt-4 w-full bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-2 rounded font-medium transition-colors"
        >
          {loading ? "Adding..." : "Add Trade"}
        </button>
      </form>
    </div>
  );
};

export default ManualTradeForm;
