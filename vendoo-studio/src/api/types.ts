/** Response shapes for the Studio FastAPI backend. Keep in sync with server/vendoo_studio/routes. */
import type { AnalyticsAds } from "./adSpend";

export type ListingData = Record<string, unknown>;

/** One inventory row. Notes stay on the full Conversation: the sidebar polls
 * every row, and only the open listing reads them. */
export interface ConversationSummary {
  id: string;
  title: string | null;
  status: string;
  /** The wholesale box this item came out of. */
  box_id?: string | null;
  settled_at?: string | null;
  unsettled_at?: string | null;
  created_at: string;
  updated_at: string;
  cover_photo_url?: string | null;
  vendoo_status?: string | null;
  vendoo_cover_url?: string | null;
  /** What the sidebar filters on: the listing's SKU and price, its Vendoo
   * labels, and the marketplaces it is live on. */
  sku?: string | null;
  price?: number | null;
  vendoo_labels?: string[];
  vendoo_marketplaces?: string[];
  /** Each marketplace listing's own page, where Vendoo recorded one. */
  vendoo_listing_urls?: Record<string, string>;
  /** Vendoo's own time tracking: when the item was created, last modified,
   * last went live (a relist moves this) and sold, plus the listing and sale
   * date per marketplace. */
  vendoo_created_at?: string | null;
  vendoo_modified_at?: string | null;
  vendoo_listed_at?: string | null;
  vendoo_sold_at?: string | null;
  vendoo_listed_dates?: Record<string, string>;
  vendoo_sold_dates?: Record<string, string>;
  /** When Studio last wrote this listing onto its Vendoo item. A marketplace
   * listed before this still shows the copy from before that write. */
  vendoo_form_updated_at?: string | null;
  /** Marketplaces owed a relist since then, kept across the delist itself. */
  vendoo_relist_pending?: string[];
  /** Edited here since Studio and Vendoo were last level: Update Vendoo is owed. */
  unsent_edits?: boolean;
}

export interface Conversation extends ConversationSummary {
  notes: string | null;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: string;
  text: string;
  provider: string | null;
  model: string | null;
  created_at: string;
}

/** Everything still running for a listing; chat is only done when ``busy`` is false. */
export interface ConversationActivity {
  busy: boolean;
  items: string[];
  message_count: number;
  last_message_id: string | null;
}

export interface Photo {
  id: string;
  conversation_id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  display_order: number;
  width: number | null;
  height: number | null;
  created_at: string;
  url: string;
}

export interface PhotoUploadResult {
  ok: boolean;
  count: number;
  photos: Photo[];
  errors?: string[];
  message?: string;
}

export interface OkResponse {
  ok: boolean;
}

export interface DeleteConversationResult extends OkResponse {
  deleted_jobs: number;
  deleted_photos: number;
}

export type ValidationIssue = Record<string, string>;

export interface ListingResponse {
  conversation_id: string;
  current_revision_id: string | null;
  listing: ListingData;
  revision_count: number;
  can_send: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  info: ValidationIssue[];
  can_send: boolean;
}

export interface ListingUpdateResult extends OkResponse {
  revision_id: string;
  validation: ValidationResult;
}

export interface ListingRevision {
  id: string;
  source: string;
  created_at: string;
  parent_revision_id: string | null;
  title: string;
}

export interface RevisionRestoreResult extends OkResponse {
  revision_id: string;
}

export interface ListingChange {
  field: string;
  before: unknown;
  after: unknown;
}

export interface SendPreview {
  review_id: string;
  revision_id: string;
  mode: "create" | "update";
  changes: ListingChange[];
  photo_count: number;
  photo_action: "keep" | "upload";
  warnings: string[];
}

export interface PriceDropHistoryEvent {
  from_price: number;
  to_price: number;
  percent: number;
  created_at: string;
  revision_id: string;
}

export interface PriceDropComps {
  available: boolean;
  text: string;
  market: string;
  market_midpoint: number | null;
  target_price: number | null;
  source: string;
  query: string;
}

/** One comps source's progress: ChatGPT, Cursor, MiMo, or the Brave fallback. */
export interface PriceDropCompsSource {
  source: string;
  state: "searching" | "done" | "failed" | "timeout" | string;
  sold: number;
  live: number;
  detail: string;
}

export interface PriceDropOption {
  price: number;
  /** The target that produced this price; the label uses effective_percent. */
  percent: number;
  effective_percent: number;
}

export interface PriceDropSellThrough {
  /** "category" | "brand" | "all" — how the cohort was picked. */
  scope: string;
  label: string;
  count: number;
  /** null when too few of those sales show what the price moved off. */
  median_discount_percent: number | null;
  /** How many of the cohort's sales carried a usable discount. */
  discount_count: number;
  median_days: number | null;
}

export interface PriceDropPreview {
  current_price: number;
  sell_through: PriceDropSellThrough | null;
  age_days: number | null;
  first_price: number;
  drop_options: PriceDropOption[];
  suggested_percent: number;
  suggested_effective_percent: number;
  suggested_price: number;
  suggested_mode: "percent" | "comps" | "sell_through" | string;
  suggested_reason: string;
  percent_options: number[];
  prices_by_percent: Record<string, number>;
  comps: PriceDropComps;
  history: PriceDropHistoryEvent[];
}

export interface PriceDropApplyResult extends OkResponse {
  revision_id: string;
  price: number;
  previous_price: number | null;
  percent: number | null;
  mode: string;
  validation: ValidationResult;
}

export interface Job {
  id: string;
  conversation_id: string;
  status: string;
  current_step: string | null;
  vendoo_item_id: string | null;
  vendoo_url: string | null;
  attempt_count: number;
  last_error: string | null;
  listing_title: string;
  mode?: string | null;
  blocker_fields?: Record<string, unknown>[] | null;
  send_progress?: { completed: number; total: number } | null;
  started_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface VendooItemResult {
  ok: boolean;
  source?: string | null;
  item_id?: string | null;
  url?: string | null;
  error?: string | null;
  api_error?: string | null;
  item?: Record<string, unknown> | null;
  form?: Record<string, unknown> | null;
  statuses?: Record<string, unknown> | null;
}

export interface ChatGPTPendingLogin {
  verification_url: string;
  user_code: string;
  error?: string | null;
}

export interface ChatGPTStatus {
  signed_in: boolean;
  email?: string | null;
  plan?: string | null;
  pending?: ChatGPTPendingLogin | null;
  error?: string | null;
}

export interface ClaudeStatus {
  /** Whether Claude Code, whose login Studio signs in with, is on this Mac. */
  installed: boolean;
  signed_in: boolean;
  email?: string | null;
  plan?: string | null;
  install_command: string;
}

export type ListingProviderId = "chatgpt" | "claude" | "mimo" | "cursor";
/** "same" reads photos with the listing provider. */
export type PhotoProviderChoice = "same" | ListingProviderId;

/** What the sidebar names each listing by. */
export type ListingNames = "title" | "sku";

export interface ProviderStatus {
  provider: string;
  primary: ListingProviderId;
  fallback: ListingProviderId | "none";
  photo_provider: PhotoProviderChoice;
  configured: boolean;
  masked_key: string | null;
  masked_cursor_key?: string | null;
  vision_model: string;
  listing_model: string;
  base_url: string;
  chatgpt: ChatGPTStatus;
  claude: ClaudeStatus;
}

export interface ProviderTestResult {
  ok: boolean;
  provider: string;
  error?: string;
}

/** One redacted Vendoo HTTP call. Query strings, tokens, and bodies are absent. */
export interface VendooApiLogEntry {
  id: number;
  at: string;
  method: string;
  host: string;
  path: string;
  status: number | null;
  duration_ms: number;
  ok: boolean;
  error: string | null;
}

export interface FillLogEntry {
  id: string;
  step: string;
  marketplace: string;
  field: string;
  status: string;
  reason: string;
  selector: string;
  value_preview: string;
}

export interface FillLogReport {
  job_id: string;
  summary: Record<string, number>;
  by_marketplace: Record<string, { summary: Record<string, number>; entries: FillLogEntry[] }>;
  log_path: string | null;
}


/** One field a marketplace form renders, as Vendoo's category schema defines it. */
export interface MarketplaceFormField {
  key: string;
  label: string;
  value: string;
  required: boolean;
  multi: boolean;
  selection_only: boolean;
  options: string[];
}

/** A marketplace's form for one listing. ``known`` is false when no schema is cached. */
export interface MarketplaceForm {
  marketplace: string;
  category_id: string;
  known: boolean;
  fields: MarketplaceFormField[];
}


/** Progress of a whole-inventory Vendoo import. */
export interface VendooBulkImport {
  running: boolean;
  total: number;
  processed: number;
  imported: number;
  updated: number;
  skipped: number;
  failed: number;
  deleted: number;
  photos: number;
  current_title: string;
  started_at: string;
  finished_at: string;
  cancelled: boolean;
  error: string;
  failures: { item_id: string; title: string; error: string }[];
}

/** Quiet pass that only refreshes draft / active / sold for bound listings. */
export interface VendooLabelSync {
  running: boolean;
  checked: number;
  updated: number;
  skipped: boolean;
  reason: string;
  started_at: string;
  finished_at: string;
  error: string;
}

export interface Suggestion {
  conversation_id: string;
  kind: SuggestionKind;
  title: string;
  reason: string;
  action: "open" | string;
  score: number;
  cover_photo_url?: string | null;
  age_days?: number | null;
}

export type SuggestionKind =
  | "failed"
  | "ready_to_generate"
  | "fix_validation"
  | "stale_active"
  | "ready_to_review";

export interface SuggestionsResponse {
  suggestions: Suggestion[];
}

export type AnalyticsRange = "7d" | "30d" | "90d" | "12m" | "all";

export interface AnalyticsInventory {
  active: number;
  draft: number;
  sold: number;
  failed: number;
  working: number;
  asking_value: number;
  cost_value: number;
  cost_known: number;
  stale_count: number;
  stale_value: number;
  undated_count: number;
}

export interface AnalyticsSales {
  count: number;
  revenue: number;
  profit: number | null;
  profit_known: number;
  fees_known: number;
  revenue_known: number;
  days_known: number;
  average_price: number | null;
  median_days: number | null;
  margin: number | null;
}

export interface AnalyticsPeriod extends AnalyticsSales {
  label: string;
}

export interface AnalyticsGroup extends AnalyticsSales {
  id: string;
  label: string;
}

export interface AnalyticsActiveListing {
  conversation_id: string;
  title: string;
  price: number;
  days_listed: number | null;
}

export interface AnalyticsAging {
  label: string;
  count: number;
  asking_value: number;
  listings: AnalyticsActiveListing[];
}

/** An active listing past 60 days, with how deep it can go and still cover its cost. */
export interface AnalyticsStaleListing {
  conversation_id: string;
  title: string;
  days_listed: number;
  price: number;
  cost: number | null;
  /** Whole dollars that return the cost after fees; null with no cost recorded. */
  lowest_price: number | null;
  /** Null when even the everyday 25% would sell below the lowest price. */
  discount_percent: number | null;
  sale_price: number | null;
}

export interface AnalyticsSale {
  conversation_id: string;
  title: string;
  price: number | null;
  marketplace: string;
  sold_at: string | null;
  days_listed: number | null;
  /** The sale event this sale fell in, if any. */
  event: string | null;
  profit: number | null;
}

export interface InventoryAnalytics {
  range: AnalyticsRange;
  last_updated_at: string | null;
  incomplete_sales: { conversation_id: string; title: string; missing: string[] }[];
  undated_sales: number;
  periods_truncated: boolean;
  inventory: AnalyticsInventory;
  sell_through_rate: number | null;
  sales: AnalyticsSales;
  previous: { start: string; end: string; sales: AnalyticsSales } | null;
  periods: AnalyticsPeriod[];
  marketplaces: AnalyticsGroup[];
  categories: AnalyticsGroup[];
  brands: AnalyticsGroup[];
  aging: AnalyticsAging[];
  stale: AnalyticsStaleListing[];
  recent: AnalyticsSale[];
  oldest: { conversation_id: string; title: string; price: number; days_listed: number }[];
  ads: AnalyticsAds;
}

export interface BackupSnapshot {
  path: string;
  name: string;
  taken_at: string;
  reason: string;
  size_bytes: number;
  compressed: boolean;
}

export interface BackupsStatus {
  snapshots: BackupSnapshot[];
  folder: string | null;
  latest: BackupSnapshot | null;
  database_bytes?: number;
  retained_bytes?: number;
  disk_free_bytes?: number;
  can_snapshot?: boolean;
  warning?: string | null;
}

export interface DatabaseTableSize {
  table: string;
  bytes: number | null;
  rows: number;
}

export interface DatabaseReport {
  path: string;
  database_bytes: number;
  tables: DatabaseTableSize[];
  ok?: boolean;
  pruned?: { vendoo_drafts: number; duplicate_events: number; deleted: number };
}

export interface SourcingComp {
  url: string;
  title: string;
  sold_at: string;
  price: number;
  marketplace: string;
  snippet: string;
  /** Set when the sale is one of the seller's own listings. */
  conversation_id?: string | null;
}

/** Everything behind one kind of box's resale estimate. */
export interface SourcingEvidence {
  theme: string;
  per_piece: number;
  sold_median: number;
  active_median: number | null;
  low: number;
  high: number;
  comps: SourcingComp[];
  active: Omit<SourcingComp, "sold_at">[];
  updated_at: string | null;
  source: string | null;
}

export interface SourcingLot {
  store: string;
  /** Shopify variant number, or a marketplace lot id. */
  variant_id: number | string;
  title: string;
  url: string;
  price: number;
  compare_at: number | null;
  pcs: number;
  pcs_estimated: boolean;
  grade: string;
  lbs: number;
  lbs_estimated: boolean;
  vip: boolean;
  listed: string | null;
  seller_resale: number | null;
  theme: string;
  /** Marketplace lots: the seller, the state it ships from, and whether shipping is in the price. */
  seller: string | null;
  origin: string | null;
  free_shipping: boolean;
  checkout_fee: number;
  ship_est: number;
  /** The carrier's list rate before the store's discount; what a bought box records. */
  ship_list: number;
  usable_pcs: number;
  demand: number;
  trend_hits: string[];
  landed: number;
  cog_per_pc: number;
  cog_per_usable_pc: number;
  resale_per_pc: number | null;
  resale_factor: number;
  sell_through: number;
  expected_revenue: number | null;
  expected_profit: number | null;
  roi: number | null;
  score: number;
  comps_count: number;
  research_at: string | null;
  research_source: string | null;
  active_median: number | null;
  resale_low: number | null;
  operating_cost: number;
  break_even_pcs: number | null;
  downside_profit: number | null;
}

export interface SourcingCart {
  store: string;
  name: string;
  subtotal: number;
  shipping: number;
  free_shipping: boolean;
  free_shipping_over: number | null;
  /** Whether the link opens a cart with the boxes in it, or the first box's own page. */
  cart_fills: boolean;
  cart_url: string;
  lots: SourcingLot[];
}

export interface SourcingBuyList {
  budget: number;
  total: number;
  expected_profit: number;
  carts: SourcingCart[];
  exclusions: Record<string, "needs_research" | "same_theme" | "return_target" | "downside" | "budget" | "alternative">;
}

export interface SourcingSeasonality {
  window: { buy_on: string; start_date: string; end_date: string; ready_in_weeks: number; selling_window_weeks: number; market: string; timezone: string };
  seller_history: {
    periods: { start_date: string; end_date: string }[];
    dated_recorded_sales: number;
    matching_window_sales: number;
    excluded_incomplete_or_invalid: number;
    minimum_group_sales: number;
    coverage: string;
    groups: {
      category_path: string;
      item_type: string | null;
      count: number;
      historical_median_price: number;
      period_counts: Record<string, number>;
      examples: { title: string; sold_at: string; sold_price: number; listing_source: string }[];
    }[];
  };
}

export interface SourcingSnapshot {
  updated_at: string;
  destination_zip: string;
  preferences: Omit<SourcingPrefs, "recent_zips">;
  stores: Record<string, { name: string; error: string | null; sellout: number | null; zone: number | null; origins: number }>;
  research: boolean;
  priced_themes: number;
  shipping: {
    residential_surcharge: number;
    fuel_surcharge_pct: number;
    fuel_surcharge_as_of: string;
    factors: Record<string, number>;
    calibration: Record<string, { factor: number | null; orders: number; needed: number }>;
  };
  assumptions: { sell_through: number; fees: number; grade_yield: Record<string, number>; cost_per_piece: number };
  buy_list: SourcingBuyList;
  store_buy_lists: Record<string, SourcingBuyList>;
  lots: SourcingLot[];
  calibration: Record<string, { factor: number | null; sales: number; needed: number }>;
  seasonality: SourcingSeasonality;
  /** What Raghouse's members-only boxes would add to this list; null when the seller is a VIP. */
  vip_upside: { boxes: number; extra_profit: number; monthly_fee: number } | null;
}

export interface SourcingPrefs {
  budget: number;
  min_roi: number;
  raghouse_vip: boolean;
  zip: string;
  recent_zips: string[];
  sell_through: number;
  fees: number;
  cost_per_piece: number;
  ready_in_weeks: number;
  selling_window_weeks: number;
}

export interface SourcingState {
  refreshing: boolean;
  research_available: boolean;
  prefs: SourcingPrefs;
  trend: { terms: string[]; updated_at: string | null; source: string | null };
  snapshot: SourcingSnapshot | null;
}

/** What a bought box, or a store's boxes together, have returned so far. */
export interface BoxTotals {
  spent: number;
  listings: number;
  listed: number;
  sold: number;
  returned: number;
  profit: number;
  roi: number | null;
  sell_through: number | null;
  unsold_asking: number;
  median_days: number | null;
}

export interface SourceBox extends BoxTotals {
  id: string;
  /** "raghouse", "tvf", or the name of any other store. */
  store: string;
  title: string;
  url: string | null;
  price: number;
  shipping: number;
  pieces: number | null;
  estimate_per_piece: number | null;
  list_shipping: number | null;
  bought_at: string | null;
  cost_per_piece: number | null;
}

export interface SourceStoreResults extends BoxTotals {
  store: string;
  boxes: number;
}

export interface SourceBoxes {
  boxes: SourceBox[];
  stores: SourceStoreResults[];
}

export interface SourceBoxInput {
  store: string;
  title: string;
  price: number;
  shipping: number;
  pieces: number | null;
  url?: string | null;
  estimate_per_piece?: number | null;
  list_shipping?: number | null;
}

export type ScoutVerdict = "buy" | "maybe" | "pass" | "unsure";

/** One "is this worth buying?" check from photos taken while sourcing. */
export interface ScoutCheck {
  id: string;
  status: "checking" | "done" | "failed";
  asking_price: number | null;
  photo_urls: string[];
  title: string | null;
  /** Expected sale price: the median of the sold comps. */
  estimate: number | null;
  comps_count: number | null;
  comps: string | null;
  error: string | null;
  decision: "bought" | "passed" | null;
  conversation_id: string | null;
  sold_price: number | null;
  created_at: string | null;
  /** What the sale brings in after marketplace fees. */
  net: number | null;
  /** The most worth paying to double the money. */
  pay_up_to: number | null;
  profit: number | null;
  verdict: ScoutVerdict | null;
}

export interface ScoutState {
  checks: ScoutCheck[];
  track_record: { checks: number; bought: number; sold: number; median_ratio: number | null; close: number };
}

