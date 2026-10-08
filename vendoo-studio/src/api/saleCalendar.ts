export type SaleMarketplace = "ebay" | "depop" | "etsy";
export type SaleEventStatus = "planned" | "ran" | "cancelled";

export interface SaleCalendarItem {
  id: string;
  title: string;
  price: number;
  cost: number | null;
  category: string;
  marketplaces: SaleMarketplace[];
  listed_at: string | null;
}

export interface SalePlan {
  title: string;
  marketplace: SaleMarketplace;
  start_date: string;
  end_date: string;
  timezone: string;
  discount_percent: number;
  fee_percent: number;
  shipping_cost: number;
  minimum_profit: number;
  item_ids: string[];
  notes: string;
}

export interface SaleTotals {
  count: number;
  revenue: number;
  profit: number | null;
  profit_known: number;
  revenue_known: number;
}

export type SaleRecord = Pick<SalePlan, "title" | "start_date" | "end_date" | "timezone" | "notes"> & { marketplace: string; discount_percent: number | null };

export interface SaleEvent extends Omit<SalePlan, "item_ids" | "marketplace" | "fee_percent" | "shipping_cost" | "minimum_profit" | "discount_percent"> {
  marketplace: string;
  fee_percent: number | null;
  shipping_cost: number | null;
  minimum_profit: number | null;
  discount_percent: number | null;
  id: string;
  status: SaleEventStatus;
  items: (SaleCalendarItem & { estimated_profit: number })[];
  result: {
    through: string;
    scope: "items" | "marketplace";
    after_days: number;
    after: SaleTotals | null;
    selected: SaleTotals;
    marketplace: SaleTotals;
    comparison: SaleTotals | null;
    comparison_start: string;
    comparison_end: string;
    comparison_unavailable: string | null;
    ongoing: boolean;
  } | null;
}

export interface SalePattern {
  marketplace: SaleMarketplace;
  weeks: number;
  sales: number;
  history_start: string;
  history_end: string;
  weekdays: { label: string; count: number; average: number | null }[];
  suggested_start: string;
  suggested_end: string;
  reason: string;
}

export interface SaleCalendarData {
  timezone: string;
  events: SaleEvent[];
  items: SaleCalendarItem[];
  patterns: SalePattern[];
}
