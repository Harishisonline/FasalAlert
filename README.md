# FasalAlert

**Microclimate decision engine for Maharashtra smallholders.** One quantified, voice-readable answer per field per day:
what to do, by when, how sure we are, and the source of every number. Built for the 21st Aavishkar Research Convention
2026-27 (University of Mumbai, TSEC) by Harish Pradhan and Raviraj Purohit.

> **Transport limitation (stated up front):** there is no public, machine-readable dataset of Indian highway
> closures. FasalAlert's road output is a *susceptibility score from rainfall and terrain*. It is not calibrated against
> closures and never means "the road will be closed".

## Using the app

**First visit:** landing page at `/` → **Get started** / **Sign in** → enter a mobile number → enter the 6-digit code
shown on the sign-in screen (local demo; see [Sign-in codes](#sign-in-codes-local-demo)) → choose a language (new
accounts) → set up your farm in four steps (location, crop, details, review; the map is optional) → Home.

**Returning user:** sign in → Home.

| Path | Who | Page |
|---|---|---|
| `/` | Anyone | Landing: product story, sources and limits, static district outlook preview |
| `/[locale]/signin` | Anyone | Sign in or create an account (OTP) |
| `/[locale]/onboarding` | Signed in | First-time farm setup (users who already have a field use Add field) |
| `/[locale]/home` | Signed in | Today's decision, weather, fields, alerts, market, road, shortcuts |
| `/[locale]/fields`, `/[locale]/fields/new` | Signed in | My Fields (search, filter, edit, delete) and Add field |
| `/[locale]/field/[id]` | Signed in | One field in detail |
| `/[locale]/ask`, `/[locale]/ask/[id]` | Signed in | Ask assistant: new conversation or a saved thread (type or speak; **Stop** cancels an in-flight answer) |
| `/[locale]/market` | Signed in | Mandi prices (real AGMARKNET data only) and the road there |
| `/[locale]/alert` | Signed in | Alert history and delivery settings |
| `/[locale]/map` | Signed in | Regional outlook: interactive district frost and heat risk |
| `/[locale]/settings`, `/[locale]/settings/calibration` | Signed in | Account, language, theme, units, alerts; per-field calibration |
| `/[locale]/offline` | Anyone | Offline fallback |

`[locale]` is `mr`, `hi` or `en`.

**Navigation**

- **Desktop (1024px+):** collapsible side nav: Overview (Home, Regional outlook), Farm (Fields with quick links, Ask,
  Market, Alerts), Account (Settings, Calibration).
- **Phones:** bottom tabs Home, Fields, Ask, Market, Alerts; **More** opens Regional outlook, Settings, Calibration,
  Sign out.
- Theme and language live under **Settings** (and on the public landing header). Guests do not open the interactive map;
  the landing page shows a static outlook preview only.

### Ask assistant

Ask is a chat about *this farmer's* fields, crops, weather, crop health, irrigation, pests, harvest, mandi prices and
roads, grounded on account/fields/decisions in the database plus verified RAG advisories.

- New conversation at `/ask`; each answered thread gets `/ask/[id]` and appears in history (searchable; delete supported).
- Scope a question to one field or all fields; **Stop answer** discards an unfinished reply (nothing is saved).
- Typing always works. Spoken input needs Bhashini or optional local Whisper.
- With `GROQ_API_KEY` set, answers are drafted by **Qwen** on Groq (`GROQ_MODEL`, default `qwen/qwen3.8-27b`) from that
  grounded context. Numbers must already appear in context; off-topic questions are refused. If Groq is unset or fails,
  the deterministic composer is used (`answer_source`: `groq` or `compose`).

## Repository

```
apps/api        FastAPI (Python 3.11): routers, decision engine, models, RAG, Groq Ask, voice, workers, migrations, scripts, tests
apps/web        Next.js 16 PWA (React 19, TypeScript strict, CSS Modules, MapLibre)
packages/shared API contract (api.ts) and the cited crop table (crops.json)
infra/db        PostgreSQL 16 + PostGIS + pgvector image
scripts/        locale-message and em-dash checks
```

## Prerequisites

Docker (Colima or Docker Desktop) with docker-compose, Python 3.11 with [uv](https://docs.astral.sh/uv/), Node 22 with
pnpm, ffmpeg (audio decoding for the voice assistant).

## Run it locally

```bash
cp .env.example .env                 # then set JWT_SECRET and OTP_PEPPER to long random strings
                                     # optional: GROQ_API_KEY for AI Ask answers
docker-compose up -d db              # PostgreSQL 16 + PostGIS + pgvector on localhost:5433

cd apps/api
uv sync
uv run alembic upgrade head          # schema
uv run python scripts/seed_locations.py
uv run python scripts/seed_crops.py
uv run python scripts/register_models.py
uv run python scripts/ingest_corpus.py      # downloads the local embedding model on first run (~once)
uv run uvicorn app.main:app --reload --port 8000        # API: http://localhost:8000/api/v1/docs

# in another terminal: background jobs (forecast refresh, decisions, public board, alerts, market, retraining)
cd apps/api && uv run python -m app.workers.scheduler

# in another terminal: web app
pnpm install
cp .env.example apps/web/.env.local   # web variables are at the bottom of the file
pnpm dev:web                          # http://localhost:3000
```

### Sign-in codes (local demo)

No SMS is sent when `SMS_PROVIDER=dev_outbox` (the default). With `DEMO_OTP_VISIBLE=true` (also the default in
`.env.example`), the API returns `demo_code` and the **sign-in screen shows the 6-digit code** with a copy button, so
you do not need a terminal or outbox file for day-to-day use or demos.

Codes expire after 5 minutes; 5 wrong attempts lock the code; at most 3 codes per hour per number, 60 s apart.
`DEMO_OTP_VISIBLE` and `dev_outbox` are refused when `APP_ENV=production`. Real SMS needs Twilio
(`SMS_PROVIDER=twilio` and the `TWILIO_*` values).

(Optional fallback for automation: codes are also written to `apps/api/data/dev_outbox/sms.jsonl`. Playwright e2e may
read that file; judges and local sign-in should use the on-screen code.)

For a production-like local run of the web app (what the browser tests use): `cd apps/web && pnpm build && PORT=3000 pnpm start`.

## Data and models

```bash
uv run python scripts/train_frost.py        # frost and heat classifier: IMD gridded archive + archived JMA forecasts
                                            # first run downloads about 693 MB (IMD files take ~80 s each); --offline reuses the cache
uv run python scripts/train_prices.py       # price models; serves only series that beat seasonal naive
uv run python scripts/import_agmarknet_csv.py FILE.csv --source-url URL --retrieved-at 2026-11-02T10:00:00+05:30
uv run python scripts/eval_rag.py --compare-embeddings
uv run python scripts/asr_report.py data/asr_eval/pairs.jsonl     # WER vs DW-WER, real transcripts only
uv run python -m app.workers.scheduler run public_board           # one-off job run
```

## Tests

```bash
cd apps/api && uv run pytest                 # backend suite against the PostGIS test database
cd apps/api && uv run pytest -m network      # live end-to-end journey (Open-Meteo, OSRM, OpenTopoData)
pnpm --filter @fasalalert/web test            # frontend unit tests
cd apps/web && pnpm typecheck && pnpm lint     # TypeScript strict and ESLint
cd apps/web && pnpm e2e                        # browser journeys (Playwright, installed Chrome); needs the API and web running
node scripts/check-messages.mjs && node scripts/check-emdash.mjs
```

## External services

| Service | Needed for | Key | Status without it |
|---|---|---|---|
| Open-Meteo | Forecasts, ensemble, ERA5 | none | n/a |
| OSRM, OpenTopoData | Routes and elevation | none (self-host OSRM for production) | n/a |
| Groq | Spoken Ask answers (Qwen) | `GROQ_API_KEY` (+ optional `GROQ_MODEL`) | Deterministic composer only |
| data.gov.in (AGMARKNET) | Live mandi prices | `DATA_GOV_IN_API_KEY` | Market shows "unavailable"; CSV import still works |
| IMD API | Official warnings, NHAI highway nowcast | `IMD_API_KEY` + URLs | FasalAlert's own transport model only |
| Bhashini | Marathi STT and TTS | `BHASHINI_USER_ID`, `BHASHINI_ULCA_API_KEY` | Typing works; optional local Whisper for STT |
| Twilio (or another SMS provider) | OTP and alerts | `TWILIO_*` | Dev outbox + on-screen demo OTP (not allowed in production) |
| Web Push | Browser alerts | `VAPID_*` (generate with `scripts/generate_vapid.py`) | Push toggle disabled |
| WhatsApp Cloud API | WhatsApp alerts | `WHATSAPP_*` | Toggle shown as unavailable |

## Deployment

Three deployable pieces: the web app (a Vercel Next.js project), the API (a Vercel Python function at the
repository root), and PostgreSQL with PostGIS and pgvector (Supabase, Neon, or any PostGIS-enabled Postgres).

**1. Database**

- **Supabase or Neon:** create a PostgreSQL 16 database, then run
  `CREATE EXTENSION postgis; CREATE EXTENSION vector; CREATE EXTENSION pgcrypto; CREATE EXTENSION pg_trgm;`.
- **Local container:** `docker compose up -d db` builds `infra/db/Dockerfile` (PostgreSQL 16 + PostGIS 3 + pgvector)
  on port 5433.
- Set `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB?sslmode=require`.
- Apply the schema and seed it (from `apps/api`):
  `uv run alembic upgrade head && uv run python scripts/seed_locations.py && uv run python scripts/seed_crops.py && uv run python scripts/register_models.py && uv run python scripts/ingest_corpus.py`.

**2. API on Vercel (Python function)**

1. Import the repository and set the Root Directory to the repository root (leave it empty), Framework to FastAPI.
2. The repository-root `vercel.json` builds the project: it runs `python apps/api/scripts/fetch_embedding_model.py`,
   which downloads the int8 ONNX embedding model (~278 MB) into the function bundle. The model is fetched at build
   time rather than committed, and the flat layout it writes keeps the bundle small.
3. The `requirements.txt` at the repository root pins the serving dependencies. It is the request-path subset of
   `apps/api/pyproject.toml`: no test, training or ingestion extras.
4. Set these variables (see `.env.example` for the full list):
   - `DATABASE_URL` (required)
   - `JWT_SECRET`, `OTP_PEPPER` (32+ random characters each; the API refuses to start in production otherwise)
   - `CORS_ORIGINS` (your web domain)
   - `APP_ENV=production`, `SMS_PROVIDER=twilio` with the `TWILIO_*` values, `DEMO_OTP_VISIBLE=false`
   - `WEB_OTP_ORIGIN` (your web domain, for SMS autofill)
   - optionally `GROQ_API_KEY` (spoken Ask answers), `VAPID_*`, `BHASHINI_*`, `IMD_API_KEY`, `DATA_GOV_IN_API_KEY`
5. `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` is required: the bundle (dependencies + embedding model) is larger than the
   standard Python limit.
6. The health check is `/api/v1/health`. `api/index.py` mounts the FastAPI app (`apps/api/app/main.py`) on every path.

**3. Web on Vercel**

1. Import the repository and set the Root Directory to `apps/web` (pnpm workspace detected).
2. `apps/web/vercel.json` keeps this project independent of the repository-root `vercel.json` used by the API.
3. Variables: `API_BASE_URL` (API URL + `/api/v1`), `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_VAPID_PUBLIC_KEY`,
   and optionally `NEXT_PUBLIC_LINKEDIN_URL`, `NEXT_PUBLIC_X_URL`, `NEXT_PUBLIC_GITHUB_URL`.
4. The service worker is served with `Cache-Control: no-cache, no-store, must-revalidate`.

**4. Background jobs**

The worker runs in its own process (`python -m app.workers.scheduler`), not inside a request. A Vercel function
is per-request, so scheduled jobs are triggered with a cron that calls a job endpoint, or run by hand from a
machine with the same environment:

```
uv run python -m app.workers.scheduler run public_board
uv run python -m app.workers.scheduler run refresh_forecasts
```

Job names: `refresh_forecasts`, `public_board`, `recompute_decisions`, `dispatch_alerts`, `market_ingest`,
`sync_registry`, `train_prices`. Every run is recorded in `job_runs` with an idempotency key, so re-running a job
for the same slot does nothing.

**The public board refreshes itself, and the weather API is cached.** Open-Meteo rate limits by IP address, and a
serverless function's egress IP is shared with every other tenant on it, so a function-hosted refresh is often
answered with 429. Two things make the board survive that:

- The raw district forecast is stored in `district_forecast_cache` whenever a fetch succeeds. A refresh that cannot
  reach the API rebuilds the board from that cache instead of failing, so the board stays live.
- `GET /api/v1/public/risks` triggers a refresh at most once an hour, claimed through `job_runs`, so a burst of
  visitors does not become a burst of upstream calls.

To seed the cache from a machine that is not rate limited, run the job once by hand against the same database:
`uv run python -m app.workers.scheduler run public_board`.

**5. After deploying**

- `curl $API/api/v1/health` shows which integrations are configured and how fresh the data is.
- Model artifacts (`apps/api/data/artifacts/`) ship with the function; retrain with `scripts/train_frost.py` and
  `scripts/train_prices.py` and redeploy.
- The advisory corpus (`apps/api/data/corpus/`) is committed, so the RAG index can be rebuilt without downloading
  ~700 MB of source documents again.

## Limitations

Read this before relying on any output. These are stated plainly on purpose.

**Transport risk is not a closure forecast.** There is no public, structured, machine-readable dataset of Indian highway
closures. FasalAlert's transport output is a **susceptibility score from rainfall and terrain**, built from IMD rainfall
categories, SRTM elevation and road class. It is not calibrated against observed closures and must never be read as "the
road will be closed".

**Crop thresholds are not yet agronomist-verified.** `packages/shared/crops.json` cites a source for every value, but all
six crops are marked `verified: false`. ICAR primary sites could not be reached during data collection, so some values
come from FAO, university papers and secondary references. Heat thresholds are missing (null) for five crops, so no heat
risk is raised for them. Spoilage factors are null, so the expected transport loss is not computed.

**Weather resolution.** Forecasts are gridded (Open-Meteo; the JMA forecast fed to the frost and heat classifier is about
0.5°, the ECMWF ensemble 0.25°), and the classifier's target is the IMD 1° cell average. It cannot see a frost pocket,
a valley bottom or a slope inside one farm. The UI says so.

**The public board can be served from a cached forecast.** Open-Meteo rate limits by IP address, and a serverless
function's egress IP is shared with every other tenant on it. When a refresh cannot reach the API, the board is rebuilt
from the forecast cached by an earlier successful fetch (`district_forecast_cache`), so the numbers shown are real but
may be a few hours older than the last successful fetch. The API reports this with `stale: true` and the board's own
timestamp. It never shows invented values: with nothing cached, the last good board is served and labelled stale.

**Frost and heat skill at the thresholds the crops actually use.** The classifier (`frost-2026.11`) has demonstrated
skill over climatology at frost 10 °C and heat 38 to 42 °C (48 h, season-bootstrap 95% interval above zero). It was also
evaluated at the crop table's own thresholds, and none of them has demonstrated skill:

| Crop threshold | Events (48 h) | Status served in `evidence.skill_status` |
|---|---|---|
| Mango flowering frost 4.4 °C | 2 | preliminary |
| Grape berry growth frost 7 °C | 52 | not demonstrated (Brier skill 0.021, 95% interval −0.270 to 0.125) |
| Cotton mid-season heat 43 °C | 436 | not demonstrated (0.095, interval −0.042 to 0.198) |
| Cotton heat override ceiling 45 °C | 28 | preliminary |
| Cotton frost −1 °C, farmer-calibrated thresholds below 4 °C | not evaluated | not evaluated |

Every frost or heat risk carries this status, and the field page states it in the reader's language. Further limits:

- Frost is trained and scored on December to February and heat on March to May. Outside those months the prediction is an
  extrapolation and its notes say so.
- The model was trained on JMA forecasts, and JMA's bias shifted over 2016 to 2025 (Tmax bias +3.9 °C in 2016 and 2017,
  about +0.5 °C later). Retrain every season (`scripts/train_frost.py`). If the JMA request fails, the default
  `best_match` forecast is passed instead; held-out skill is lower with it, and the evidence records `forecast_model`.
- There is no untouched test set: the design was revised using the same held-out seasons, so the reported skill is mildly
  optimistic.
- Observed lags, ensemble spread and station distance are not used (no real-time IMD grid, no archived ensemble).

**Decisions are refreshed every 6 hours.** `GET /decisions/today` serves today's stored decision; the
`recompute_decisions` worker job rebuilds it every 6 hours (and the first request of the day computes it). A decision can
therefore lag the newest forecast by up to 6 hours. The decision's `sources` carry the forecast fetch time.

**Prices.** Mandi locations come from AGMARKNET 2.0's market list ("APMC Pune" style names, town-level coordinates). The
data.gov.in price feed may spell markets differently; the join between the two has not been checked because no
`DATA_GOV_IN_API_KEY` is configured. No real AGMARKNET history is loaded until `DATA_GOV_IN_API_KEY` is set or official CSV
exports are imported. Until then the price model is unavailable and the UI shows that honestly. Seeded synthetic rows, if
anyone creates them in development, are labelled "Sample data" and excluded from training.

**Voice.** Live Marathi STT and TTS need Bhashini credentials (or a local Whisper model for STT). Without them, the
assistant works by typing and the client offers browser speech only when a Marathi voice exists. No DW-WER benchmark
score has been measured yet: that needs real recordings with human reference transcripts.

**Advisory corpus.** Answers quote only verified institutional sources. "Verified" here means the publishing institution is
trusted and the document's provenance (URL, hash, licence evidence) is recorded. It does not yet mean a human agronomist
has reviewed each chunk; that review is the next step for the corpus. Many sources are in English; Marathi users then see
an English quote marked "original source in English". No machine translation is used.

Answers are extractive: the composer quotes whole sentences chosen by keyword overlap with the question, with actionable
sentences ranked first. On the 20 answerable evaluation questions it composed 18 answers. Reading those quotes, 6 are
clearly actionable advice and 2 partly; the rest are relevant background rather than an instruction. One is wrong for its
question: "What irrigation schedule should grapes get after fruit pruning?" is answered with a frost-protection sentence
about pruning, because the indexed corpus has no grape irrigation advice and the composer only checks for a shared topic
word. Two Marathi questions (sugarcane watering, heatwave care) abstain because no quotable sentence shares a word with
the expanded question.

Devanagari text extracted from PDFs is searched but never quoted. The ICAR-NSRI, ICAR-NRCP and ICAR-CICR PDFs use legacy
font encodings that extract as garbled text, and a garbled dose is unsafe to show. Marathi and Hindi quotes need Unicode
sources or a reviewed transcription.

**Public board.** District risks are computed at each district's centroid for every tracked crop at its typical stage this
season. The board does not know which crops are actually grown in each district. A district's reason sentence states the
model's corrected estimate for the risk it names; the Tmin and Tmax columns show the raw forecast, so the two numbers can
differ.

**Rate limiting.** The public board limiter is in-process; multiple API replicas need a shared limiter.

**Web app and first decisions.** A new field's first decision takes about 20 s (live forecast, 51-member ensemble, JMA run,
road route and elevations). Home, My Fields and the field page stream and refresh themselves while it is worked out; the
wait is real. API requests hold a database connection while they wait on upstream services. The pool was raised to 30
connections to keep the development stack responsive; a production deployment should move upstream fetches out of request
transactions. Which fields are being recomputed in the background is tracked inside one API process, so with several API
replicas a second replica can compute the same first decision again (correct, slower). The list endpoint (`GET /fields`)
does not compute a degree-day stage (soybean) until the field's first decision has stored it; until then the stage reads
"being worked out". Account deletion has no API, so the app offers none (individual fields can be deleted). Marathi and
Hindi strings added in the redesign have not yet been reviewed by a native speaker.

## Data credits

Weather data by [Open-Meteo.com](https://open-meteo.com) (CC BY 4.0), with ERA5 and ECMWF IFS ensemble data from ECMWF and
JMA GSM forecasts. Gridded temperature and rainfall for training: India Meteorological Department, Pune.
Routes © OpenStreetMap contributors (ODbL), routed with OSRM. Elevation SRTM via OpenTopoData. Mandi prices: AGMARKNET,
Government of India. District boundaries and place names: Wikidata (CC0), geoBoundaries ADM2 and ADM3 (ODbL 1.0) and OSM
(ODbL 1.0), as recorded in the `source` field of each file under `apps/api/data/geo/`. Advisory sources: ICAR institutes
(ICAR-NRCP, ICAR-CICR, ICAR-NSRI, ICAR-ISRI, ICAR-NRCG), State Agricultural Universities and FAO; every document's
institution, source URL, licence, licence evidence URL, SHA-256 and retrieval timestamp are recorded per row in
`apps/api/data/corpus/manifest.jsonl`.

## Links

LinkedIn, X (Twitter) and GitHub links for the team are configured with `NEXT_PUBLIC_LINKEDIN_URL`, `NEXT_PUBLIC_X_URL`
and `NEXT_PUBLIC_GITHUB_URL` and appear in the landing page footer and the Settings About block.
