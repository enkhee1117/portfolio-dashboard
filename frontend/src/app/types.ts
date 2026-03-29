export interface Trade {
    id: string;
    date: string;
    ticker: string;
    type: string;
    side: string;
    price: number;
    quantity: number;
    fees: number;
    currency: string;
    expiration_date?: string;
    strike_price?: number;
    option_type?: string;
    is_wash_sale?: boolean;
}

export interface PortfolioSnapshot {
    date: string;
    ticker: string;
    quantity: number;
    average_price: number;
    current_price: number;
    market_value: number;
    unrealized_pnl: number;
    realized_pnl: number;
    realized_pnl_ytd?: number;
    primary_theme?: string | null;
    secondary_theme?: string | null;
}

export interface Asset {
    ticker: string;
    price: number;
    primary_theme: string;
    secondary_theme: string;
    last_updated?: string | null;
    previous_close?: number | null;
    daily_change?: number | null;
    daily_change_pct?: number | null;
}

export interface ThemeLists {
    primary: string[];
    secondary: string[];
}

export interface PortfolioHistoryPoint {
    date: string;
    value: number;
}

export interface ThemeBasketSeries {
    name: string;
    stocks: number;
    start_value: number;
    end_value: number;
    return_pct: number;
    data: { date: string; value: number }[];
}

export interface ThemeBasketResponse {
    themes: ThemeBasketSeries[];
}
