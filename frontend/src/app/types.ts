export interface Trade {
    id: number;
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
    primary_theme?: string | null;
    secondary_theme?: string | null;
}
