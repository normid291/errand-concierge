# Errand Concierge

**AWS Agents for Humans Hackathon submission**

Errand Concierge is a conversational AI agent that helps you manage errands, appointments, and small tasks through natural chat — parse a messy brain-dump into organized items, reschedule things by saying "push the dentist to Friday," mark things done, and sync everything to your Google Calendar automatically.

Built with the [Strands Agents SDK](https://github.com/strands-agents), running on AWS Bedrock via a custom OpenAI-compatible endpoint (Bedrock Mantle), with a FastAPI backend and a hand-built vanilla HTML/CSS/JS frontend.

**Live demo:** https://errand-concierge.vercel.app
**Backend API:** https://errand-concierge-production.up.railway.app

---

## What it does

- **Chat-based errand capture** — dump a list of things you need to do in plain language, and the agent parses and adds each one individually.
- **Natural rescheduling** — "move rent to next week," "push the dentist to Friday."
- **Status tracking** — mark errands done, cancel them, or reopen them.
- **Trash tab** — deleted errands are soft-logged with a snapshot and timestamp before being hard-deleted from the active list, so you can see what you removed.
- **Google Calendar sync** — connecting your Google account (Calendar-only OAuth scope) automatically creates, updates, and deletes matching calendar events as you add, reschedule, or cancel errands through chat.
- **Live-state awareness** — since errands can also be managed directly through the sidebar UI (buttons hit the backend directly, bypassing the chat agent), the agent always re-fetches the current errand list before answering questions about what's pending, rather than trusting its own conversation memory.

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent framework | Strands Agents SDK |
| Model | `openai.gpt-oss-120b` via AWS Bedrock Mantle (`bedrock-mantle.us-east-1.api.aws`) — a non-standard, OpenAI-compatible Bedrock endpoint, used because the classic Bedrock runtime API was blocked on the AWS account this was built with |
| Backend | Python, FastAPI |
| Storage | Flat JSON files (`tasks.json`, `tasks_trash.json`) — no database, single-user demo scope |
| Calendar integration | Google OAuth 2.0 (Calendar-events scope only), Google Calendar API v3 |
| Frontend | Vanilla HTML/CSS/JavaScript, no framework or build step |
| Backend hosting | Railway |
| Frontend hosting | Vercel |

---

## Project structure

```
errand-concierge/
├── agent.py                  # Strands Agent definition, system prompt, model config
├── backend.py                 # FastAPI app: chat endpoint, errand CRUD, serves frontend
├── tools.py                    # @tool-decorated functions the agent can call
├── storage.py                  # JSON file read/write for tasks
├── calendar_tools.py           # Google Calendar sync helpers (create/update/delete events)
├── google_auth.py               # Google OAuth flow + token storage/refresh
├── integrations_routes.py       # FastAPI routes for the Google OAuth connect/callback/status flow
├── main.py                      # CLI entry point for testing the agent directly
├── test_agent.py                 # Standalone script for a quick agent sanity check
├── app.py                        # Alternate Streamlit-based local UI (not used in production deploy)
├── requirements.txt               # Python dependencies
├── .env.example                    # Documents required environment variables
├── .gitignore                       # Excludes secrets and local data files
└── frontend/
    ├── index.html                    # Main UI markup
    ├── style.css                      # All styling
    ├── app.js                          # Chat, errand grid, Google integration UI logic
    ├── vercel.json                      # Rewrites /static/* to match Vercel's flat file layout
    └── assets/
        ├── logo-mark.png                 # Icon-only logo (sidebar + masthead)
        └── logo-full.png                  # Full wordmark logo (unused currently)
```

---

## Building it: what we did, in order

### 1. Core agent and chat backend
Set up the Strands `Agent` with a system prompt defining the concierge persona and five tools: `add_errand`, `list_errands`, `reschedule_errand`, `complete_errand`, `cancel_errand`. Wired the model to AWS Bedrock Mantle's OpenAI-compatible endpoint since the account's classic Bedrock runtime access was blocked. Built a FastAPI backend (`backend.py`) exposing `/api/chat` and errand CRUD endpoints, and a custom HTML/CSS/JS frontend served directly by FastAPI via `StaticFiles`.

### 2. Bug fixes during development

**Date miscalculation bug.** The agent was computing explicit calendar dates itself (e.g. confidently stating the wrong day of the week for a given date), because it was trying to do date arithmetic internally instead of trusting the underlying date parser. Fixed by rewriting the system prompt so the agent passes relative date phrases ("tuesday," "next friday") straight through to the tools untouched, and never rewrites them into an explicit date itself. The system prompt is also now built dynamically at runtime (`build_system_prompt()`) so it's always grounded in the real current date.

**Stale-memory bug.** The sidebar's delete/complete/cancel buttons call the backend's REST endpoints directly, bypassing the chat agent entirely. Since the `Agent` object is a long-lived singleton holding conversation history, it could confidently describe errands as still pending after they'd already been changed through the sidebar. Fixed with a system-prompt rule: whenever the user asks about current errands, or references one by name, the agent must call `list_errands` fresh rather than trusting anything said earlier in the conversation — except immediately after the agent itself just called a mutating tool in that same turn.

**Duplicate-errand refusal bug.** A related issue surfaced during testing: if an errand was added via chat, then deleted through the sidebar, and the user then asked the agent to add the exact same errand again, the agent would refuse, saying "you already have this," based purely on its own conversational memory of having added it earlier — without checking whether it still actually existed. Fixed with an explicit system-prompt rule: never refuse or flag a duplicate based on conversation memory; only call it out as an existing errand if `list_errands` was called in that same turn and it's confirmed still present.

**Debug print statements.** Removed leftover `print()` debugging statements from `tools.py`'s `add_errand` function and, later, from all of `calendar_tools.py` (parsing, event creation, update, and token-header helper functions all had `[calendar debug]`-prefixed prints).

**Reschedule producing zero-duration calendar events.** Found and fixed a real bug while cleaning up `calendar_tools.py`: `update_calendar_event` was setting a rescheduled event's start and end time to the exact same timestamp, producing a zero-duration event, and was missing the `timeZone` field that `create_calendar_event` correctly included. Fixed to compute a one-hour end time and include the timezone, matching the create path.

### 3. Feature additions

- **Trash tab**: hard-deleting an errand still fully removes it from `tasks.json`, but a snapshot with a deletion timestamp is now logged to `tasks_trash.json` first. Added a `GET /api/errands/trash` endpoint and a 🗑️ Trash item in the sidebar, rendering deleted errands as read-only cards with a "Deleted" badge.
- **Status badge colors**: color-coded badges for Pending (yellow), Done (green), Cancelled (red), and Trash (grey), with matching CSS custom properties for washes and solid colors.
- **Branding**: replaced a placeholder inline SVG mascot with a real supplied logo, cropped to an icon-only transparent version for the sidebar and masthead. Added the tagline "Your plans. Our priority."
- **Visual polish pass**: colored icon badges on the feature cards (Stay on Track / Reliable / Save Time / Peace of Mind), a pill-shaped date badge in the masthead, a handwritten-style "Less stress / More done" annotation using the Google Font Caveat, and a custom notepad-and-pen SVG illustration next to the welcome message.

### 4. Security hardening before going public

Several rounds of cleanup were needed here, documented honestly because mistakes were made and caught along the way:

- Moved the Bedrock API key out of a hardcoded literal in `agent.py` into an environment variable, loaded via `python-dotenv`'s `load_dotenv()` at startup, so the real key only ever lives in a local `.env` file (never committed) or in the hosting platform's environment variable settings.
- Confirmed `google_auth.py` already read its Google OAuth credentials from environment variables with only harmless placeholder fallbacks — no code change needed there.
- Found a real hardcoded Bedrock API key in `test_agent.py` (a separate quick-test script) that had been missed in the first pass. Fixed it the same way, and rotated the exposed key in the AWS Bedrock console as a precaution once it had been in a local commit.
- Built a proper `.gitignore` excluding `.env`, `tokens.json`, `tasks.json`, `tasks_trash.json`, `__pycache__/`, and virtual environment folders — after first catching that `git status` was being run from the *home directory* rather than the project folder, which would have tracked unrelated personal files (AWS credentials folder, shell history, unrelated scripts) alongside the project.
- When first pushing to GitHub, **GitHub's push protection correctly blocked the push** because it detected a real AWS-format key inside a committed file (`test_agent.py`). The key was rotated, the file fixed, and the entire local git history was reset (`rm -rf .git` and a fresh `git init`) before re-pushing cleanly, since simply fixing the file in a new commit would have left the exposed key sitting in an earlier commit's history forever.

### 5. Deployment

**Backend — Railway** (originally planned for Render, switched after Render started requiring card verification even on its free tier during setup; Railway's trial credit required no card):
- Created a new project from the GitHub repo.
- Set the start command to `python backend.py`.
- Added environment variables: `BEDROCK_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `ALLOWED_ORIGINS`.
- Generated a public Railway domain.
- Hit and fixed, in order: a missing `requirements.txt` (dependencies were never actually committed, causing `ModuleNotFoundError: No module named 'fastapi'`), a circular import between `tools.py` → `calendar_tools.py` → `google_auth.py` caused by a stray import that had been introduced while editing files locally, and finally a batch of environment variables that had been set to their own variable *names* instead of their real secret values (e.g. `GOOGLE_CLIENT_ID`'s value was literally the text `GOOGLE_CLIENT_ID`), plus a `GOOGLE_REDIRECT_URI` that had never been updated off `localhost`. Once all four were corrected to real values, both chat and Google Calendar connected successfully.

**Frontend — Vercel:**
- Imported the GitHub repo with root directory set to `frontend/`, no build step (static site).
- After deploying, the entire page rendered as unstyled plain HTML with broken image icons. Root cause: `index.html` references all assets under `/static/...` paths (`/static/style.css`, `/static/app.js`, `/static/assets/logo-mark.png`), because locally `backend.py` mounts the whole `frontend` folder under a `/static` URL prefix via `StaticFiles`. Vercel has no such mapping and serves the folder's real file structure directly, so every asset 404'd. Fixed with a `vercel.json` rewrite rule redirecting any `/static/*` request to the matching real path.
- Fixed a mobile layout bug where the masthead (logo, heading, and a flex-row date-pill-plus-handwritten-note block) had no responsive wrapping rule, causing the note and date pill to be squeezed off the right edge of the screen on narrow viewports. Added a mobile breakpoint that lets the masthead wrap and stack, and hides the purely decorative handwritten note entirely on very narrow phone screens.

---

## Environment variables

See `.env.example` for the full list. In short:

| Variable | Purpose |
|---|---|
| `BEDROCK_API_KEY` | Auth key for the Bedrock Mantle OpenAI-compatible endpoint |
| `GOOGLE_CLIENT_ID` | Google OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth 2.0 client secret |
| `GOOGLE_REDIRECT_URI` | Must exactly match an Authorized redirect URI configured in Google Cloud Console |
| `ALLOWED_ORIGINS` | CORS allow-list for the frontend's domain |
| `PORT` | Set automatically by Railway; the app reads this instead of a hardcoded port |

---

## Running it locally

```bash
git clone https://github.com/normid291/errand-concierge.git
cd errand-concierge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root (see `.env.example`) with your real `BEDROCK_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` (use `http://localhost:8000/api/integrations/google/callback` for local testing).

```bash
python backend.py
```

Visit `http://localhost:8000`.

### Google Calendar setup (required for the calendar sync feature)

1. In Google Cloud Console, enable the **Google Calendar API** for your project.
2. Create an OAuth 2.0 Client ID (type: Web application).
3. Add `http://localhost:8000/api/integrations/google/callback` as an authorized redirect URI (and your production callback URL, if deploying).
4. Add your own Google account as a **Test user** under the OAuth consent screen — this app stays in "Testing" publish status, which is fine for a demo and doesn't require Google's app verification review.

---

## Known limitations

- **Single-user by design.** There's no login or account system — one shared `tokens.json` file represents "the" connected Google account for the whole app. Anyone who opens the deployed URL sees the same connected calendar. This was a deliberate scope decision for a hackathon demo, not an oversight.
- **Timezone is hardcoded** to `Africa/Lagos` in `calendar_tools.py`, matching the developer's own timezone for the demo. Would need to be made configurable for real multi-region use.
- **No persistent database** — task storage is flat JSON files on disk. On Railway's free tier, the filesystem is not guaranteed to persist across redeploys, so errand data may reset when the service restarts or redeploys.

---

## Deployment notes for reference

- **Backend (Railway):** watches the GitHub repo's `main` branch and auto-redeploys on push.
- **Frontend (Vercel):** same — watches `main` and auto-redeploys on push, root directory set to `frontend/`.
- If the Railway URL ever changes, update `frontend/app.js`'s `API_BASE` constant and push.
- If the Vercel URL ever changes, update the `ALLOWED_ORIGINS` environment variable on Railway to match, and update the Google Cloud Console authorized redirect URI to use the current Railway callback URL.
