# Anthology — Project Reference

*Current as of 12 May 2026 (bootstrap API server added — Flask endpoint on port 5050 triggers orientation generation immediately after onboarding). Use this document when starting a new context window.*

---

## What This Is

**Anthology** is a personalised, LLM-generated newspaper. The end state: each user receives a daily edition of content generated specifically for them — dispatches, essays, notes — calibrated to their analytical profile and domain interests. No two users receive the same content. The UI presents this as a newspaper front page, not a feed.

Live site: `https://anthology-weld.vercel.app`
GitHub repo: `DonovanBerry11/anthology` (private)
Deployed via Vercel (auto-deploys on push to main).

---

## Where Everything Lives

### Mac (development and interactive use)

| Folder | Purpose |
|---|---|
| `~/Desktop/anthology/` | The website: HTML, CSS, publish scripts, HTML generators |
| `~/Desktop/analytical-system/` | Agent infrastructure: skills, orientation files, user registry, queues, audits |

### Digital Ocean Server (autonomous publishing — runs 24/7)

| Path | Purpose |
|---|---|
| `/root/anthology/` | Clone of `DonovanBerry11/anthology` |
| `/root/anthology-system/` | Clone of `DonovanBerry11/anthology-system` |
| `/root/pipeline/` | Cron-invoked shell scripts that run the daily pipeline |
| `/root/pipeline/bootstrap_server.py` | Flask bootstrap API server (port 5050) |
| `/root/anthology-env/` | Python 3.12 virtual environment with all dependencies |
| `/root/.anthology.env` | Credentials file (chmod 600) — all secrets stored here |
| `/root/anthology/.publish-config` | GitHub PAT (single line plain text) |
| `/etc/cron.d/anthology` | Cron job definitions |
| `/etc/systemd/system/anthology-bootstrap.service` | Systemd unit for the bootstrap API server |

---

## Key Infrastructure

### Vercel

Auto-deploys on every push to `main` of `DonovanBerry11/anthology`. No manual deploy step needed. URL rewrites configured in `vercel.json` for `/users/:id/{section}/:slug` content paths.

### GitHub

Two private repos:

| Repo | Contents |
|---|---|
| `DonovanBerry11/anthology` | Website HTML/CSS/JS, publish scripts, content directories, catalogs, edition.json files |
| `DonovanBerry11/anthology-system` | Queues, orientation files, pieces (analysis.md, log.md), indexes, dispatch-standards.md, scripts |

The server clones `anthology` to `/tmp/anthology-*-publish/` for each publish operation (avoids lock issues), commits the new HTML + updated catalog/edition, and pushes. Vercel picks up the push and deploys automatically.

**Git identity on server:** `anthology-server@digitalocean` / `Anthology Server`

**Important:** The Mac Cowork tasks and the server cron jobs both write to the same GitHub repo. Do not run both simultaneously — disable the Cowork scheduled tasks once the server pipeline is confirmed stable.

### Supabase

- URL: `https://uzjkepauhgbuunvcokru.supabase.co`
- Anon key: `sb_publishable_eBmXtZ0QxVcdethdAy2NSg_-izzQaoJ`
- Auth: PKCE flow, email/password + magic link
- User metadata stored on `user_metadata` (set by onboarding questionnaire at signup):

| Field | Type | Description |
|---|---|---|
| `country_of_residence` | string | Selected from dropdown or free-text "Other" |
| `city` | string | Selected from dropdown or free-text "Other" |
| `country_of_origin` | string | Selected from dropdown or free-text "Other" |
| `interests` | string[] | One or more of: Politics, Foreign Affairs, Economics, Finance, Tech, Sports, Entertainment |
| `additional_info` | string | Optional free-text (max 500 chars) |
| `reading_interests` | string | Composite string built from the above fields — consumed by the pipeline keyword-scorer and homepage feed ranking |
| `onboarding_complete` | boolean | Set to `true` on questionnaire completion; prevents re-showing the flow |

#### Database Schema

All tables must be created manually in the Supabase SQL editor.

##### `reading_events`
Tracks per-user reading behaviour for orientation calibration.
```sql
CREATE TABLE reading_events (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL,
  piece_slug text NOT NULL,
  piece_type text NOT NULL,
  read_depth_percent integer,
  time_on_page_seconds integer,
  created_at timestamptz DEFAULT now()
);
```

##### `content_pieces`
Stores autonomous agent output before and after publishing.
```sql
CREATE TABLE content_pieces (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL,
  slug text NOT NULL UNIQUE,
  type text NOT NULL CHECK (type IN ('essay', 'note', 'dispatch', 'uk-politics', 'us-sports')),
  title text NOT NULL,
  body text NOT NULL,
  standfirst text,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  sector text,
  domain text,
  generated_at timestamptz DEFAULT now(),
  published_at timestamptz,
  created_at timestamptz DEFAULT now()
);
```

##### `agent_logs`
Tracks agent actions for debugging autonomous pipelines.
```sql
CREATE TABLE agent_logs (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid,
  task_id text,
  action text NOT NULL,
  detail text,
  status text NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error', 'warn')),
  created_at timestamptz DEFAULT now()
);
```

#### Supabase Permissions

Run these in the Supabase SQL Editor. Required for server-side pipeline to function.

```sql
GRANT INSERT ON public.agent_logs TO service_role;
GRANT INSERT, SELECT ON public.reading_events TO service_role;
GRANT SELECT, INSERT, UPDATE ON public.content_pieces TO service_role;
```

**Note:** `GRANT SELECT ON reading_events TO service_role` was added 2026-05-12 — required by `update_orientation.py` when called from the server with the service role key.

### Digital Ocean

- **Droplet:** `ubuntu-s-1vcpu-2gb-lon1` — Ubuntu 24.04.4 LTS, 1 vCPU, 2 GB RAM, London datacenter
- **IP:** `159.65.80.203`
- **Access:** `ssh root@159.65.80.203`
- **Purpose:** Runs the autonomous publishing pipeline via cron and the Bootstrap API Server (port 5050).

#### Server Credentials File (`/root/.anthology.env`)

```
ANTHROPIC_API_KEY=<anthology-server key from console.anthropic.com>
GITHUB_TOKEN=<PAT>
SUPABASE_URL=https://uzjkepauhgbuunvcokru.supabase.co
SUPABASE_ANON_KEY=sb_publishable_eBmXtZ0QxVcdethdAy2NSg_-izzQaoJ
SUPABASE_SERVICE_KEY=<service_role key from Supabase dashboard → Settings → API>
SUPABASE_KEY=<same as SUPABASE_SERVICE_KEY — required by register_new_users.py>
ANTHOLOGY_DIR=/root/anthology
SYSTEM_DIR=/root/anthology-system
```

#### Server Software Stack

| Component | Version | Notes |
|---|---|---|
| Ubuntu | 24.04.4 LTS | |
| Python | 3.12.3 | |
| pip | 24.0 | |
| Node.js | 20.20.2 | Required for Claude Code |
| npm | 10.8.2 | |
| Claude Code | 2.1.139 | Installed globally via `npm install -g @anthropic-ai/claude-code` |
| Git | 2.43.0 | Identity: `anthology-server@digitalocean` |
| Python venv | `/root/anthology-env/` | Activated in all pipeline scripts |

Python packages in venv: `anthropic`, `supabase`, `requests`, `python-dotenv`, `flask`, `flask-cors` and dependencies.

---

### Bootstrap API Server

A lightweight Flask server running continuously on the droplet. Called by `onboarding.html` in a fire-and-forget fetch immediately after saving `user_metadata` to Supabase. Triggers `bootstrap_orientation.py` to generate `orientation.md` and register the user without waiting for the 4:38 AM cron.

| Property | Value |
|---|---|
| **Endpoint** | `POST http://159.65.80.203:5050/bootstrap` |
| **Auth** | `Authorization: Bearer <supabase_session_access_token>` — validated against `GET {SUPABASE_URL}/auth/v1/user`; `user_id` in body must match JWT |
| **Request body** | `{"user_id": "<supabase uuid>"}` |
| **Success response** | HTTP 200 `{"status": "ok", "message": "<stdout>"}` |
| **Error responses** | 400 bad body · 401 unauthorized · 429 rate limited · 500 bootstrap failed · 504 timeout (30s) |
| **Source file** | `/root/pipeline/bootstrap_server.py` |
| **Systemd service** | `anthology-bootstrap` |
| **Request log** | `/root/anthology-system/logs/bootstrap-server.log` |
| **Journal log** | `journalctl -u anthology-bootstrap -f` |
| **Port** | 5050 |
| **CORS** | `https://anthology-weld.vercel.app`, `http://localhost` |
| **Rate limit** | 3 requests per `user_id` per hour (in-memory dict — resets on server restart) |

**Initial deployment:** Run `~/Desktop/anthology/deploy_bootstrap.command` (double-click in Finder, or `bash ~/Desktop/anthology/deploy_bootstrap.command` in Terminal). Installs Flask/flask-cors into the venv, deploys `bootstrap_server.py` and the systemd unit, enables and starts the service.

**After updating `bootstrap_server.py`:**
```bash
scp ~/Desktop/anthology/bootstrap_server.py root@159.65.80.203:/root/pipeline/
ssh root@159.65.80.203 "systemctl restart anthology-bootstrap"
```

**Startup / verification commands (run via SSH):**
```bash
# Enable and start
systemctl daemon-reload
systemctl enable anthology-bootstrap
systemctl start anthology-bootstrap

# Check status
systemctl status anthology-bootstrap --no-pager -l

# View live journal log
journalctl -u anthology-bootstrap -f

# Test endpoint (expect 401 with placeholder token)
curl -s -X POST http://localhost:5050/bootstrap \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test-token" \
  -d '{"user_id": "00000000-0000-0000-0000-000000000000"}'

# Health check
curl -s http://localhost:5050/health
```

---

### Users Registry

**Mac path:** `~/Desktop/analytical-system/users/registry.json`
**Server path:** `/root/anthology-system/users/registry.json`

Maps Supabase UUIDs to orientation file paths. The server version has paths set to `/root/anthology-system/...` (not the Mac Desktop paths). Currently one user:

- **Donovan Berry** — UUID `94baf514-f988-464f-8de1-56c29d4597ee`
- **Mac orientation:** `~/Desktop/analytical-system/users/donovan/orientation.md`
- **Server orientation:** `/root/anthology-system/users/donovan/orientation.md`

**Important:** The `registry.json` in GitHub has Mac paths. After any `git pull` on the server, re-run the path fix:
```bash
sed -i 's|/Users/donovanberry/Desktop/analytical-system/|/root/anthology-system/|g' /root/anthology-system/users/registry.json
```

---

## Server Pipeline (`/root/pipeline/`)

The server runs the same pipeline as the Cowork scheduled tasks but fully autonomously — no laptop required. Each script sources `/root/.anthology.env` for credentials.

| Script | Cron time (UTC) | What it does |
|---|---|---|
| `run_news_scout.sh` | 4:06 AM | Calls Claude Code with web search to find 6–7 news topics; appends to `NEWS_TOPIC_QUEUE.md`. Skips if ≥10 PENDING already queued. |
| `run_topic_scout.sh` | 4:19 AM | Calls Claude Code with web search to find 4–5 analytical directives; appends to `DIRECTIVE_QUEUE.md`. Skips if ≥10 PENDING. |
| `run_register_users.sh` | 4:38 AM | Runs `register_new_users.py --env /root/.anthology.env` — syncs confirmed Supabase users into registry. |
| `run_update_orientations.sh` | 4:41 AM | Reads registry for active users, runs `update_orientation.py` with `SUPABASE_SERVICE_KEY` for each. |
| `run_dispatch.sh` | 5:07 AM | Main pipeline: queue depth check → topic selection → 5 dispatches + 3 notes per user → publish → regenerate edition.json → update tracking files. |

All cron logs append to `/root/anthology-system/logs/cron-[task].log`. Per-run structured logs go to `/root/anthology-system/logs/[task]-YYYY-MM-DD.md`.

#### Claude Code Permission Mode

All Claude-calling scripts use `--permission-mode auto`. The `--dangerously-skip-permissions` flag is blocked by Claude Code when running as root.

#### Cron File (`/etc/cron.d/anthology`)

```
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

6  4 * * * root /root/pipeline/run_news_scout.sh >> /root/anthology-system/logs/cron-news-scout.log 2>&1
19 4 * * * root /root/pipeline/run_topic_scout.sh >> /root/anthology-system/logs/cron-topic-scout.log 2>&1
38 4 * * * root /root/pipeline/run_register_users.sh >> /root/anthology-system/logs/cron-register-users.log 2>&1
41 4 * * * root /root/pipeline/run_update_orientations.sh >> /root/anthology-system/logs/cron-update-orientations.log 2>&1
7  5 * * * root /root/pipeline/run_dispatch.sh >> /root/anthology-system/logs/cron-dispatch.log 2>&1
```

UTC times correspond to the Cowork schedule (which runs in BST/UTC+1): 4:06 UTC = 5:06 BST, etc.

#### Updating Pipeline Scripts

To update a script, edit it on the Mac, scp it over, and re-run setup:
```bash
scp /path/to/updated/run_X.sh root@159.65.80.203:/root/pipeline/
chmod +x /root/pipeline/run_X.sh
```

#### Keeping Server Repos In Sync

The server does not auto-pull from GitHub. If you push changes to `anthology-system` from the Mac, pull them on the server manually:
```bash
ssh root@159.65.80.203
cd /root/anthology-system && git pull
# Re-apply the registry path fix if registry.json was changed:
sed -i 's|/Users/donovanberry/Desktop/analytical-system/|/root/anthology-system/|g' /root/anthology-system/users/registry.json
```

For `anthology` (the website repo), the server clones fresh to `/tmp/` for each publish — no manual pull needed.

---

## Cowork Scheduled Tasks (Mac — run while laptop is on)

These tasks remain configured in Cowork but should be **disabled** once the server pipeline is confirmed stable, to avoid simultaneous writes to the GitHub repo.

| Task ID | Time (BST) | Status |
|---|---|---|
| `news-scout-daily` | 5:06 AM | Active — disable when server confirmed |
| `topic-scout-daily` | 5:19 AM | Active — disable when server confirmed |
| `register-new-users` | 5:38 AM | Active — disable when server confirmed |
| `update-orientations` | 5:41 AM | Active — disable when server confirmed |
| `dispatch-autonomous-workflow` | 6:07 AM | Active — disable when server confirmed |
| `anthology-autonomous-essay` | One-time | Disabled |
| `anthology-autonomous-workflow` | Daily | Disabled (superseded) |

---

## Site Structure (`~/Desktop/anthology/`)

### Pages
| File | Purpose |
|---|---|
| `index.html` | Homepage — masthead, nav, edition view (auth'd), catalog sections |
| `login.html` | Sign in form |
| `signup.html` | Registration form |
| `onboarding.html` | Post-signup questionnaire — 5 steps: country of residence, city, country of origin, interests (checkboxes), additional context. Saves structured `user_metadata` to Supabase; sets `onboarding_complete: true`; fires bootstrap fetch to port 5050; redirects to `/`. |
| `account.html` | Reading interests textarea + sign out |
| `about.html` | About page |
| `auth/auth.js` | Supabase client init, `_supabase` global, `updateAuthNav()`, `requireAuth()` |
| `auth/callback.html` | PKCE redirect handler post-email-confirmation. New users (no `onboarding_complete` flag) → `/onboarding.html`; returning users → `/`. |
| `style.css` | All CSS — CSS variables: `--bg`, `--text`, `--muted`, `--rule`, `--sans`, `--serif` |
| `vercel.json` | `cleanUrls`, `trailingSlash: false`, rewrites for `/users/:id/{section}/:slug` |
| `bootstrap_server.py` | Source for the droplet's Bootstrap API server — deploy via `deploy_bootstrap.command` |
| `anthology-bootstrap.service` | Systemd unit source — deploy via `deploy_bootstrap.command` |
| `deploy_bootstrap.command` | Double-click to deploy bootstrap server to the droplet (installs Flask, copies files, enables service) |

### Content Directories (in GitHub repo)
```
essays/           shared essay HTML
notes/            shared note HTML
dispatches/       shared dispatch HTML
uk-politics/      shared UK politics briefing HTML
us-sports/        shared US sports briefing HTML
users/{user_id}/
  essays/
  notes/
  dispatches/
  uk-politics/
  us-sports/
  content-catalog.json    per-user catalog
  edition.json            daily editorial hierarchy
shared-catalog.json       shared catalog (all pieces, all users; serves unauthenticated users)
```

### Python Scripts
| Script | What it does |
|---|---|
| `generate_essay_html.py` | Markdown → styled essay HTML. Args: `--input --output --slug --title --date [--pub-datetime]` |
| `generate_note_html.py` | Same for notes. PIECE_TYPE=`note` in beacon. |
| `generate_dispatch_html.py` | Same for dispatches. Extra args: `--dispatch-type [daily\|weekly] [--label] [--back-url]`. PIECE_TYPE=`dispatch`. |
| `generate_edition.py` | Builds `edition.json` from catalog. Args: `--user-id --repo-dir` (or `--catalog --output`). Selects lead, 2-3 secondary, up to 8 further reading. |
| `catalog_utils.py` | Shared helper. `update_catalog(repo_dir, entry, user_id=None)` — upserts shared + per-user catalog. |
| `publish_essay.py` | Clones repo → generates HTML (shared + per-user) → updates catalogs → commits/pushes. Args: `--slug --title --date --standfirst --analysis-md --token-file --scripts-dir [--repo] [--user-id] [--date-iso] [--sector]` |
| `publish_note.py` | Same pattern as essay. |
| `publish_dispatch.py` | Same + `--dispatch-type`. |
| `publish_uk_politics.py` | Same + `--sector politics`. |
| `publish_us_sports.py` | Same + `--sport [NBA\|NFL\|etc]`. |

Scripts that operate on the analytical-system live in `anthology-system/scripts/`:

| Script | What it does |
|---|---|
| `update_orientation.py` | Reads `reading_events` from Supabase, appends calibration block to orientation file. Args: `--user-id --registry --supabase-url --supabase-key [--days 30]`. Uses service_role key on server (anon key lacks SELECT on reading_events). |
| `register_new_users.py` | Syncs confirmed Supabase auth users → local registry + orientation files. Args: `--registry --users-dir [--env] [--dry-run]`. Reads `SUPABASE_KEY` (service role) from `--env` file. Reads structured onboarding fields (`country_of_residence`, `city`, `country_of_origin`, `interests[]`, `additional_info`) from `user_metadata` and writes a rich Stated Preferences section into `orientation.md`. Falls back to legacy `reading_interests` free-text for pre-onboarding users. |
| `bootstrap_orientation.py` | Generates `orientation.md` for a single new user immediately after they complete the onboarding questionnaire. Called at the end of the onboarding flow (not on a cron schedule); designed to complete in under 5 seconds. Fetches the user by UUID from the Supabase admin API (`GET /auth/v1/admin/users/{user_id}`), parses structured `user_metadata`, writes `orientation.md` to `{system_dir}/users/{user_id}/orientation.md`, and registers the user in `registry.json` if not already present. Args: `--user-id` (required) `--env` (default: `~/Desktop/anthology/.env`) `--system-dir` (default: `~/Desktop/analytical-system`) `--dry-run`. Reads `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from env file or environment. |

**All publish scripts clone to `/tmp/anthology-*-publish/`, work there, then push.**

### HTML Generators — Tracking Beacon
All three generators embed a reading beacon before `</body>`:
- Loads `@supabase/supabase-js@2` CDN + `/auth/auth.js`
- Records to `reading_events`: fires at scroll ≥50% depth and on `pagehide`
- Silent, non-blocking, only fires if `_supabase.auth.getSession()` returns a session

---

## Content Catalog Format

`shared-catalog.json` (shared) and `content-catalog.json` (per-user, at `users/{user_id}/`):
```json
{
  "pieces": [
    {
      "slug": "my-slug",
      "type": "essay",
      "section": "essays",
      "domain": "global",
      "sector": "political-economy",
      "title": "...",
      "standfirst": "...",
      "date": "2026-05-10",
      "date_display": "May 2026",
      "url": "/essays/my-slug.html",
      "keywords": []
    }
  ]
}
```
Per-user entries have `url` pointing to `/users/{user_id}/{section}/{slug}.html`.

---

## Edition Format

`users/{user_id}/edition.json`:
```json
{
  "date": "2026-05-10",
  "date_display": "Sunday, 10 May 2026",
  "generated_at": "10 May 2026, 7:04 AM EST",
  "user_id": "...",
  "lead": { "...piece entry..." },
  "secondary": [ "...2-3 pieces..." ],
  "further_reading": [ "...up to 8 pieces..." ]
}
```

---

## Signup Flow (end-to-end)

1. User fills out `signup.html` → Supabase sends verification email.
2. User clicks link → `auth/callback.html` exchanges PKCE code for session.
3. `callback.html` checks `user_metadata.onboarding_complete`: if absent → `/onboarding.html`; if true → `/`.
4. `onboarding.html` — 5 steps: country of residence (searchable dropdown) → city (searchable dropdown) → country of origin (searchable dropdown) → interests (checkboxes: Politics, Foreign Affairs, Economics, Finance, Tech, Sports, Entertainment) → additional context (optional textarea).
5. On submit: saves structured fields + composite `reading_interests` string + `onboarding_complete: true` to `user_metadata` via `_supabase.auth.updateUser()`.
6. Immediately fires a fire-and-forget `fetch` to `POST http://159.65.80.203:5050/bootstrap` with the user's session token — triggers `bootstrap_orientation.py` on the server to generate `orientation.md` and register the user. The redirect to `/` does not wait for this call to complete.
7. Redirects to `/`.
8. `register_new_users.py` still runs at 4:38 AM but skips users already in the registry.

---

## Homepage Logic (`index.html`)

1. Masthead date set from `new Date()`.
2. `updateAuthNav()` — nav shows "Account" → `/account.html` when signed in; "Sign in" → `/login.html` when not.
3. `buildFeed()` runs on load:
   - Gets Supabase session
   - If authenticated: tries `/users/{id}/content-catalog.json`, falls back to `/shared-catalog.json`
   - If authenticated + `/users/{id}/edition.json` fetches OK: populates `#edition` section
   - Always populates `#notes-list`, `#essays-list`, `#dispatches-list` from catalog
   - uk-politics and us-sports pieces are merged into the dispatches list with appropriate labels
4. Feed ordering: scored by keyword overlap with `session.user.user_metadata.reading_interests`, then date desc.

---

## Analytical-System Structure (`anthology-system/`)

### Skills (`.skill` files — on Mac only)
| Skill | Trigger | What it does |
|---|---|---|
| `analytical-agent.skill` | "new directive", "write an analysis" | Long-form essay pipeline: DRAFT → QUALITY CYCLE → DIALOGUE → REVISE → PUBLISH |
| `dispatch-agent.skill` | "run a dispatch", "draft a briefing" | Dispatch pipeline for all 3 domains: DRAFT → QUALITY CYCLE → PUBLISH |
| `news-scout.skill` | "scout dispatches", "populate the topics queue" | Finds dispatch topics, writes to `NEWS_TOPIC_QUEUE.md` |
| `topic-scout.skill` | "what should I write about", "find me a topic" | Finds essay directives, writes to `DIRECTIVE_QUEUE.md` |
| `architecture-audit.skill` | "run the architecture audit" | Audits system against newspaper end state |
| `user-experience-audit.skill` | "UX audit" | Maps capabilities to UI; identifies gaps |

### Orientation Files
- `users/donovan/orientation.md` — Donovan's full analytical profile
- `dispatch-standards.md` — Format, voice, and editorial standards for all dispatches

### Queues and Indexes
- `NEWS_TOPIC_QUEUE.md` — Dispatch topics: PENDING → ACTIVE → COMPLETE/STRANDED
- `DIRECTIVE_QUEUE.md` — Essay directives (same status flow)
- `dispatches-index.yaml` — Authoritative record and dimensional metadata for all dispatches
- `pieces-index.md` — All essays and notes

### Audits
- `audits/architecture-audit-2026-05-10.md`
- `audits/ux-audit-2026-05-10.md`

---

## Piece Directory Convention

Essays: `analytical-system/pieces/e[NNN]-[slug]/`
Notes: `analytical-system/pieces/n[NNN]-[slug]/`
Dispatches: `analytical-system/pieces/dispatches/d[NNN]-[slug]/`
UK politics: `analytical-system/pieces/uk-politics/p[NNN]-[slug]/`
US sports: `analytical-system/pieces/us-sports/s[NNN]-[slug]/`

Each piece dir contains: `analysis.md`, `log.md`, `review.md` (post quality cycle).

---

## Known Gaps (Priority Order)

1. **Cowork tasks and server cron both active** — both pipelines write to the same GitHub repo. Until the Cowork tasks are disabled, there is a risk of simultaneous git push conflicts if both run on the same morning. Disable the Cowork scheduled tasks once the server pipeline has run successfully for 2–3 consecutive days.
2. **registry.json path drift** — the server's `registry.json` has `/root/anthology-system/` paths. Any `git pull` from the Mac (which commits `/Users/donovanberry/Desktop/analytical-system/` paths) will overwrite these. Re-apply the sed fix after every pull (see Server section above). Long-term fix: make `update_orientation.py` accept a base directory override rather than using hardcoded paths from the registry.
3. **`content_pieces` and `agent_logs` tables** — must be created manually in Supabase SQL editor if not already done.
4. **Shared file race conditions (multi-user)** — `shared-catalog.json` is written by individual publish scripts, creating a concurrent write risk at scale. Acceptable now; centralise at scale.
5. **`DISPATCHES_ORIENTATION.md` missing** — referenced by interactive `news-scout` skill but does not exist. Scheduled task is unaffected (criteria embedded inline).
6. **Note directive reuse window** — no mechanism prevents reuse after the 3-day window expires. Resolves naturally with a deep queue (target: 15+ PENDING).
7. **Bootstrap server rate-limit is in-memory** — resets on service restart. Acceptable at current scale; use Redis if multi-process/multi-server deployment needed.

Previously resolved gaps:
- ~~No signup → registry automation~~ — `register_new_users.py` handles this (2026-05-11)
- ~~Edition empty state missing~~ — `#edition` shows message with link to set interests (2026-05-11)
- ~~No onboarding redirect~~ — full 5-step onboarding questionnaire at `/onboarding.html`; `callback.html` routes new users there post-verification; structured `user_metadata` written to Supabase; `register_new_users.py` reads fields into orientation files (2026-05-12)
- ~~1 dispatch + 1 note per user per morning~~ — 5 dispatches + 3 notes with inline QC (2026-05-11)
- ~~Pipeline only runs when laptop is on~~ — Digital Ocean server pipeline operational (2026-05-12)
- ~~Orientation generation delayed until 4:38 AM cron~~ — Bootstrap API server on port 5050 generates orientation immediately after onboarding completes (2026-05-12)

---

## Publishing a Piece (Quick Reference)

### From Mac
```bash
python3 ~/Desktop/anthology/publish_essay.py \
  --slug my-slug --title "My Title" --date "May 2026" \
  --standfirst "One sentence." \
  --analysis-md ~/Desktop/analytical-system/pieces/e001-my-slug/analysis.md \
  --token-file ~/Desktop/anthology/.publish-config \
  --scripts-dir ~/Desktop/anthology \
  --user-id 94baf514-f988-464f-8de1-56c29d4597ee
```

### From Server
```bash
source /root/anthology-env/bin/activate
python3 /root/anthology/publish_essay.py \
  --slug my-slug --title "My Title" --date "May 2026" \
  --standfirst "One sentence." \
  --analysis-md /root/anthology-system/pieces/e001-my-slug/analysis.md \
  --token-file /root/anthology/.publish-config \
  --scripts-dir /root/anthology \
  --user-id 94baf514-f988-464f-8de1-56c29d4597ee
```

After publishing, regenerate edition:
```bash
TOKEN=$(cat /root/anthology/.publish-config)
CLONE_DIR=/tmp/anthology-edition-publish
git clone https://$TOKEN@github.com/DonovanBerry11/anthology.git $CLONE_DIR
source /root/anthology-env/bin/activate
python3 /root/anthology/generate_edition.py \
  --user-id 94baf514-f988-464f-8de1-56c29d4597ee \
  --repo-dir $CLONE_DIR
git -C $CLONE_DIR add users/94baf514-f988-464f-8de1-56c29d4597ee/edition.json
git -C $CLONE_DIR commit -m "Edition: $(date +%Y-%m-%d)"
git -C $CLONE_DIR push
```
