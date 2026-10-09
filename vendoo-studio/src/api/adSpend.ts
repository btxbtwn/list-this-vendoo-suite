export type AdMarketplace = "poshmark" | "etsy";

/** What the seller copied from Promoted Closet or Etsy Ads for a stretch of days. */
export interface AdSpendInput {
  marketplace: AdMarketplace;
  start_date: string;
  end_date: string;
  spend: number;
  clicks: number | null;
  /** Orders and revenue the dashboard credits to the ads, not every sale. */
  orders: number | null;
  revenue: number | null;
  notes: string;
}

export interface AdSpendEntry extends AdSpendInput {
  id: string;
  roas: number | null;
  cost_per_click: number | null;
}

export interface AdMarketplaceTotals {
  id: string;
  entries: number;
  spend: number;
  clicks: number | null;
  orders: number | null;
  revenue: number | null;
  roas: number | null;
  cost_per_click: number | null;
  /** Every recorded sale on the marketplace in the range, with or without ads. */
  sales_revenue: number;
  spend_percent: number | null;
}

export interface AnalyticsAds {
  spend: number;
  profit_after_ads: number | null;
  marketplaces: AdMarketplaceTotals[];
}
