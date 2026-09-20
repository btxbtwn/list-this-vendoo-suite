/** Response shapes for the Studio FastAPI backend. Keep in sync with server/vendoo_studio/routes. */

export type ListingData = Record<string, unknown>;

export interface Conversation {
  id: string;
  title: string | null;
  notes: string | null;
  status: string;
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
  /** Vendoo's own time tracking: when the item was created, last modified,
   * last went live (a relist moves this) and sold, plus the listing and sale
   * date per marketplace. */
  vendoo_created_at?: string | null;
  vendoo_modified_at?: string | null;
  vendoo_listed_at?: string | null;
  vendoo_sold_at?: string | null;
  vendoo_listed_dates?: Record<string, string>;
  vendoo_sold_dates?: Record<string, string>;
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

export interface PriceDropPreview {
  current_price: number;
  first_price: number;
  suggested_percent: number;
  suggested_price: number;
  suggested_mode: "percent" | "comps" | string;
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

export type ListingProviderId = "chatgpt" | "mimo" | "cursor";

export interface ProviderStatus {
  provider: string;
  primary: ListingProviderId;
  fallback: ListingProviderId | "none";
  configured: boolean;
  masked_key: string | null;
  masked_cursor_key?: string | null;
  vision_model: string;
  listing_model: string;
  base_url: string;
  chatgpt: ChatGPTStatus;
}

export interface ProviderTestResult {
  ok: boolean;
  provider: string;
  error?: string;
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
  photos: number;
  current_title: string;
  started_at: string;
  finished_at: string;
  cancelled: boolean;
  error: string;
  failures: { item_id: string; title: string; error: string }[];
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

export interface BackupSnapshot {
  path: string;
  name: string;
  taken_at: string;
  reason: string;
  size_bytes: number;
}

export interface BackupsStatus {
  snapshots: BackupSnapshot[];
  folder: string | null;
  latest: BackupSnapshot | null;
}
