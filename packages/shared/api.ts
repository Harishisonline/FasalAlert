/**
 * FasalAlert API contract (base path /api/v1). Source of truth: PRD §11.
 * Shapes the PRD fixes (decision §11.1, abstention §11.2, error §13, auth bodies) are copied exactly.
 * Shapes the PRD leaves open ("district risk rows", "price band", ...) are defined here and mirrored
 * by the Pydantic schemas in apps/api/app/schemas. Additive fields beyond the PRD are marked ADDITIVE.
 */

export type Locale = 'en' | 'mr' | 'hi';
export type RiskLevel = 'none' | 'low' | 'medium' | 'high' | 'critical';
export type RiskKind = 'frost' | 'heatwave' | 'heavy_rain' | 'dry_spell' | 'transport';
export type Crop = 'mango' | 'pomegranate' | 'grape' | 'soybean' | 'cotton' | 'sugarcane';
export type AbstainReason =
  | 'no_retrieval_above_threshold'
  | 'model_confidence_below_threshold'
  | 'data_stale'
  | 'missing_field_input'
  | 'outside_domain';
/** ADDITIVE (inside `evidence`): demonstrated = Brier skill 95% interval above zero at this threshold. */
export type SkillStatus = 'demonstrated' | 'not_demonstrated' | 'preliminary' | 'not_evaluated';
/** How a number was produced. ADDITIVE (carried inside `evidence`). */
export type Method = 'model' | 'rule' | 'observed' | 'unavailable';
export type ISODate = string; // "2026-01-18"
export type ISODateTime = string; // "2026-01-17T21:30:00+05:30"
export type Localized = { en: string; mr: string; hi: string };

/* ---------- §13 error envelope ---------- */
/** OTP verify failures: details = { field: "code", reason: "wrong" | "expired" | "no_code" | "locked", attempts_left?: number }. */
export interface ApiError {
  error: {
    code:
      | 'validation_error'
      | 'unauthenticated'
      | 'forbidden'
      | 'not_found'
      | 'rate_limited'
      | 'data_stale'
      | 'model_unavailable'
      | 'internal_error';
    message: string;
    details: Record<string, unknown>; // validation_error: { field }, rate_limited: { retry_after }
    trace_id: string;
  };
}

export interface SourceRef {
  label: string;
  url?: string | null;
  fetched_at: ISODateTime;
  kind?: 'forecast' | 'observed' | 'advisory' | 'market' | 'model' | 'synthetic'; // ADDITIVE
  synthetic?: boolean; // ADDITIVE: true for source='synthetic_seed' (PRD §10.1, AC 7)
}

/* ---------- Public board ---------- */
// GET /public/risks?date=YYYY-MM-DD
export interface PublicDistrictRisk {
  district_id: number;
  code: string; // joins to the boundary GeoJSON feature property `code`
  name: Localized;
  level: RiskLevel | 'nodata';
  kind: RiskKind | null;
  probability: number | null; // 0..1
  tmin_c: number | null; // coldest forecast in the window
  tmin_at: ISODateTime | null;
  tmax_c: number | null; // hottest forecast in the window
  tmax_at: ISODateTime | null;
  threshold_c: number | null;
  crop: Crop | null; // crop whose threshold drives the level
  stage: string | null;
  reason: Localized | null; // AC 18: cites the threshold. null when nodata
}
export interface PublicRisksResponse {
  date: ISODate;
  generated_at: ISODateTime;
  stale: boolean;
  model_version: string;
  sources: SourceRef[];
  districts: PublicDistrictRisk[]; // all districts, nodata included
}
// GET /public/districts/{id}
export interface PublicDistrictDetail extends PublicDistrictRisk {
  band_low_c: number | null;
  band_high_c: number | null;
  affected_crops: { crop: Crop; stage: string; kind: RiskKind; threshold_c: number; level: RiskLevel }[];
  sources: SourceRef[];
  generated_at: ISODateTime;
  stale: boolean;
}

/* ---------- Auth ---------- */
export interface OtpRequestBody { phone: string } // E.164, +91XXXXXXXXXX
/**
 * `delivery` (ADDITIVE): present when the code was written to the dev SMS outbox, not sent.
 * `demo_code` (ADDITIVE): the live 6-digit code, only when DEMO_OTP_VISIBLE + dev_outbox + non-production.
 */
export interface OtpRequestResponse {
  expires_in: number;
  retry_after: number;
  delivery?: 'dev_outbox';
  demo_code?: string;
}
export interface OtpVerifyBody { phone: string; code: string }
export interface OtpVerifyResponse {
  access_token: string;
  refresh_token: string;
  user: User;
  is_new_user: boolean; // ADDITIVE: drives the R2 language step
  has_fields: boolean; // ADDITIVE: R3 vs R8 redirect
}
export interface RefreshBody { refresh_token: string }
export interface RefreshResponse { access_token: string; refresh_token: string }

/* ---------- Users ---------- */
export interface Preferences {
  channels: { whatsapp: boolean; sms: boolean; push: boolean };
  quiet_hours_start: string | null; // "22:00"
  quiet_hours_end: string | null;
  channel_availability: { whatsapp: boolean; sms: boolean; push: boolean }; // ADDITIVE: provider configured?
  sms_dev_outbox?: boolean; // ADDITIVE: development only, SMS goes to the dev outbox file, not to a phone
}
export interface User {
  id: number;
  phone_masked: string; // "+91 98•••••210" (full phone never returned)
  name: string | null;
  role: 'farmer' | 'fpo_manager' | 'admin';
  preferred_locale: Locale;
  temp_unit: 'celsius' | 'fahrenheit';
  area_unit: 'hectare' | 'acre';
  district_kvk: { name: string; phone: string } | null; // ADDITIVE
}
export interface UserMeResponse extends User { preferences: Preferences }
export interface UserPatchBody { name?: string; preferred_locale?: Locale; temp_unit?: User['temp_unit']; area_unit?: User['area_unit'] }
export interface PreferencesPatchBody {
  channels?: Partial<Preferences['channels']>;
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  push_subscription?: { endpoint: string; keys: { p256dh: string; auth: string } } | null; // ADDITIVE (Web Push)
}

/* ---------- Locations ---------- */
export interface LocationItem { id: number; name: Localized; lat?: number; lon?: number }
// GET /locations/districts | /locations/talukas?district_id= | /locations/villages?taluka_id=
/** ADDITIVE: GET /locations/search?q= (village name in any of the three languages). */
export interface VillageSearchHit extends LocationItem { taluka: LocationItem; district: LocationItem }
/** ADDITIVE: GET /locations/nearest?lat=&lon= (404 when no village lies within about 25 km). */
export interface NearestVillage { village: LocationItem; taluka: LocationItem; district: LocationItem; distance_km: number }

/* ---------- Fields and phenology ---------- */
export interface StageSummary {
  stage: string | null; // null = stage unknown (no sowing date)
  stage_label: Localized | null;
  gdd_cum: number | null;
  method: 'gdd' | 'calendar_days' | 'calendar' | null;
  next_stage: string | null;
  next_stage_label: Localized | null;
  next_stage_expected_on: ISODate | null;
  next_stage_plus_minus_days: number | null;
  explanation: Localized | null; // why the engine thinks this stage
  timeline: { key: string; label: Localized; start: ISODate; end: ISODate }[]; // 12-month window
}
export interface Field {
  id: number;
  name: string;
  crop: Crop;
  variety: string | null;
  sowing_date: ISODate | null;
  lat: number;
  lon: number;
  area_sqm: number | null;
  village_id: number | null;
  taluka_id: number | null;
  district_id: number | null;
  primary_mandi: string | null;
  location_label: Localized | null; // "Malegaon Bk, Baramati, Pune"
  stage: StageSummary;
}
/** `variety` is the crops.json variety key, e.g. "alphonso". */
export interface FieldCreateBody {
  crop: Crop; variety?: string; sowing_date?: ISODate; lat: number; lon: number; name?: string;
  village_id?: number; taluka_id?: number; district_id?: number; area_sqm?: number;
}
export type FieldPatchBody = Partial<FieldCreateBody> & { primary_mandi?: string };
export interface FieldDetail extends Field { risks: Risk[]; last_decision: Decision | Abstention | null }
// DELETE /fields/{id} (ADDITIVE): 204; the field and its decisions, risks, alerts and calibration are removed.

export interface Calibration {
  field_id: number;
  sensitivity: 'low' | 'normal' | 'high';
  frost_threshold_c: number | null; // null = use the ICAR/default value
  heat_threshold_c: number | null;
  harvest_lead_hours: number;
  defaults: { frost_threshold_c: number | null; heat_threshold_c: number | null; source: string; min_frost_c: number | null; max_heat_c: number | null }; // ADDITIVE
  lead_hours_by_sensitivity: { low: number; normal: number; high: number }; // ADDITIVE
}
export type CalibrationPatchBody = Partial<Pick<Calibration, 'sensitivity' | 'frost_threshold_c' | 'heat_threshold_c' | 'harvest_lead_hours'>>;

/* ---------- §11.1 decision (exact) ---------- */
export interface Risk {
  kind: RiskKind;
  level: RiskLevel;
  probability: number;
  tmin_c?: number | null;
  band_low_c?: number | null;
  band_high_c?: number | null;
  threshold_c?: number | null;
  window_start?: ISODateTime | null;
  window_end?: ISODateTime | null;
  lead_hours?: number | null;
  model_version: string;
  /** skill_status: how well the frost/heat classifier is shown to work at this threshold (48 h, held-out seasons;
   *  fewer than 30 events = preliminary). forecast_model: the forecast fed to the classifier. */
  evidence: Record<string, unknown> & { method?: Method; forecast_source?: string; forecast_fetched_at?: ISODateTime;
    forecast_model?: string; skill_status?: SkillStatus };
}
export interface MarketSummary {
  commodity: string; market: string; modal_rs_qtl: number; median_5d: number | null;
  forecast_p10: number | null; forecast_p50: number | null; forecast_p90: number | null;
  trend_7d_pct: number | null; baseline: string | null; beats_baseline_pct: number | null;
  arrival_qtl: number | null; expected_transport_loss_rs_qtl: number | null; source: string;
  price_date?: ISODate; horizon_days?: number | null; forecast_available?: boolean; // ADDITIVE
}
export interface TransportSummary {
  route_name: string; p_disruption_72h: number; rain_accum_mm_72h: number; harvest_deadline: ISODate | null;
  model_version: string; note: string; source: string;
}
export interface Decision {
  field_id: number;
  decision_date: ISODate;
  headline: string;
  action_text: string;
  action_by: ISODateTime | null;
  confidence: number;
  abstain_reason: null;
  risks: Risk[];
  market: MarketSummary | null;
  transport: TransportSummary | null;
  recommendation: { harvest_on: ISODate | null; sell_at: string | null; hold_until: ISODate | null; net_reason: string } | null;
  advisory: { text: string; source: string; source_url: string; institution: string; year: number | null; verified: boolean; similarity: number } | null;
  sources: SourceRef[];
  model_versions: Record<string, string>;
  limitations?: string[]; // ADDITIVE: honest-limit statements to display
}
/* ---------- §11.2 abstention (exact) ---------- */
export interface Abstention {
  field_id: number;
  decision_date: ISODate;
  headline: string;
  action_text: string;
  confidence: 0;
  abstain_reason: AbstainReason;
  risks: Risk[];
  kvk: { name: string; phone: string } | null;
  last_update?: ISODateTime | null; // ADDITIVE: for data_stale
}
export const isAbstention = (d: Decision | Abstention): d is Abstention => d.abstain_reason !== null;

// GET /decisions/today?locale=  (also honours Accept-Language; falls back to the user's preferred_locale)
// Alerts are written in the user's preferred_locale at creation time.
export type DecisionsTodayResponse = (Decision | Abstention)[];
// GET /fields/{id}/decisions?days=30
export interface DecisionHistoryItem {
  decision: Decision | Abstention;
  outcome: { status: 'confirmed' | 'did_not_happen' | 'pending'; observed_value_c?: number | null; source?: string | null; observed_on?: ISODate | null };
  alerts: { id: number; kind: string; level: RiskLevel; message: string; feedback: -1 | 1 | null }[];
}
// GET /risks/active?field_id=
export type ActiveRisksResponse = Risk[];

/* ---------- Weather ---------- */
// GET /weather/forecast?field_id=&days=7
export interface ForecastRow {
  valid_date: ISODate; tmin_c: number | null; tmax_c: number | null; rain_mm: number | null; precip_prob: number | null;
  issued_at: ISODateTime; lead_hours: number; source: string; fetched_at: ISODateTime;
}
export interface ForecastResponse { field_id: number; rows: ForecastRow[]; stale: boolean; source: SourceRef }

/* ---------- Market ---------- */
// GET /market/prices?commodity=&market=&days=90
export interface PricePoint { date: ISODate; min_rs_qtl: number | null; modal_rs_qtl: number | null; max_rs_qtl: number | null; arrival_qtl: number | null; source: string }
export interface PricesResponse { commodity: string; market: string; series: PricePoint[]; last_date: ISODate | null; synthetic: boolean; sources: SourceRef[] }
// GET /market/forecast?commodity=&market=&days=7
export interface PriceForecastResponse {
  commodity: string; market: string;
  available: boolean;
  unavailable_reason: 'no_history' | 'cold_start' | 'not_beating_baseline' | 'model_missing' | null;
  horizon_days: number;
  points: { date: ISODate; p10: number; p50: number; p90: number }[];
  baseline: 'seasonal_naive';
  beats_baseline_pct: number | null;
  historical_range: { low: number; high: number; from: ISODate; to: ISODate } | null;
  model_version: string | null;
  trained_at: ISODateTime | null;
}
// GET /market/mandis?district_id=&commodity=[&field_id=]
export interface Mandi { id: number; name: string; commodity: string; district_id: number | null; lat: number | null; lon: number | null; distance_km: number | null }

/* ---------- Transport ---------- */
// GET /transport/risk?field_id=&days=7
export interface TransportRiskResponse {
  field_id: number;
  available: boolean;
  unavailable_reason: 'route_unknown' | 'elevation_missing' | 'forecast_stale' | null;
  route_name: string | null;
  days: { date: ISODate; p_disruption: number; level: RiskLevel; rain_mm: number | null }[];
  harvest_deadline: ISODate | null;
  note: string; // "Risk estimated from rainfall and terrain, not from observed closures."
  model_version: string | null;
  computed_at: ISODateTime | null;
  official_warning: { text: string; issued_at: ISODateTime; source: string; url: string | null } | null; // IMD NHAI highway warning when configured (PRD §9.3)
  calibrated: false; // ADDITIVE: susceptibility score, never calibrated against closures
}
// GET /transport/segments?field_id=
export interface RouteSegment { id: number; name: string | null; road_class: string; length_km: number | null; min_elev_m: number | null; max_elev_m: number | null; coordinates: [number, number][] }
export interface SegmentsResponse { field_id: number; mandi: string | null; segments: RouteSegment[]; attribution: string }

/* ---------- Ask ---------- */
/** thread_id and request_id are ADDITIVE: the conversation to add to (none starts one) and a client id used by Stop. */
export interface AskBody { text?: string; audio_b64?: string; audio_mime?: string; field_id?: number; locale: Locale; thread_id?: number; request_id?: string }
export interface AnswerCardRow { label: string; value: string; source: SourceRef }

/* ---------- Assistant conversations (ADDITIVE) ---------- */
// GET /ask/threads?q=&limit=&cursor=  GET|PATCH|DELETE /ask/threads/{id}  POST /ask/cancel {request_id}
export type SavedAnswer = Pick<AskResponse, 'answer' | 'cards' | 'sources' | 'abstain' | 'abstain_reason' | 'kvk' | 'intent' | 'answer_audio_url' | 'transcript' | 'low_confidence_terms' | 'asr_confidence'>;
export interface ChatMessage { id: number; role: 'user' | 'assistant'; content: string; created_at: ISODateTime; field_id: number | null; spoken: boolean; response: SavedAnswer | null }
export interface ChatThreadSummary { id: number; title: string; pinned: boolean; field_id: number | null; created_at: ISODateTime; last_activity_at: ISODateTime; message_count: number; snippet: string }
export interface ChatThreadPage { items: ChatThreadSummary[]; next_cursor: string | null }
export interface ChatThreadDetail extends ChatThreadSummary { messages: ChatMessage[] }
export interface AskResponse {
  answer: string;
  answer_audio_url?: string | null; // path relative to the API origin, e.g. "/api/v1/ask/audio/<32 hex>" (WAV, needs the Bearer token; the web app uses /api/proxy)
  cards: AnswerCardRow[];
  abstain?: boolean;
  sources: SourceRef[];
  asr_confidence?: number | null;
  dw_wer?: number | null;
  transcript?: string | null; // ADDITIVE: what was heard (audio input)
  low_confidence_terms?: { text: string; domain_term: boolean }[]; // ADDITIVE
  abstain_reason?: AbstainReason | null; // ADDITIVE
  kvk?: { name: string; phone: string } | null; // ADDITIVE
  intent?: string | null; // ADDITIVE
  asks_remaining?: number | null; // ADDITIVE (20/day limit, PRD §12)
  stt_available?: boolean; // ADDITIVE
  // ADDITIVE (conversation history): where this exchange was saved; cancelled when Stop arrived first.
  thread_id?: number | null;
  thread_title?: string | null;
  user_message?: ChatMessage | null;
  assistant_message?: ChatMessage | null;
  cancelled?: boolean;
}

/* ---------- Alerts ---------- */
export interface AlertDelivery { channel: string; status: 'queued' | 'sent' | 'failed' | 'read'; created_at: ISODateTime; provider: string | null; error: string | null }
/** Alert kinds; UI filter chips map Heat = heatwave, Rain = heavy_rain. */
export type AlertKind = RiskKind | 'price';
export interface Alert {
  id: number; field_id: number | null; field_name: string | null; decision_id: number | null;
  kind: AlertKind; level: RiskLevel; message: string; channel: string;
  sent_at: ISODateTime | null; read_at: ISODateTime | null; feedback: -1 | 1 | null; created_at: ISODateTime;
  deliveries: AlertDelivery[];
  queued_until: ISODateTime | null; // ADDITIVE: quiet-hours release time
  detail: { advisory?: Decision['advisory']; risk?: Risk | null; action_by?: ISODateTime | null } | null; // ADDITIVE
}
// GET /alerts?kind=&status=   POST /alerts/{id}/read   POST /alerts/{id}/feedback {value: -1 | 1}
export interface AlertsResponse { alerts: Alert[]; unread: number }

/* ---------- FPO ---------- */
export interface FpoMe { id: number; name: string; district_id: number | null; member_count: number; my_role: 'member' | 'manager' }
export interface FpoPost { id: number; kind: 'question' | 'advisory' | 'announcement'; title: string; body_md: string; locale: Locale; pinned: boolean; author_name: string | null; created_at: ISODateTime }
export interface FpoPostBody { kind: FpoPost['kind']; title: string; body_md: string; locale: Locale; pinned?: boolean }

/* ---------- Health ---------- */
export interface HealthResponse {
  status: 'ok' | 'degraded';
  models: { name: string; version: string; trained_at: string | null; status: 'serving' | 'fallback' | 'unavailable' }[];
  data_freshness: { source: string; last_fetched_at: ISODateTime | null; stale: boolean }[];
  integrations: Record<string, 'configured' | 'not_configured'>; // ADDITIVE
}
