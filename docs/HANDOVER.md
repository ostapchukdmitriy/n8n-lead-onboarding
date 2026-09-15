# Handover document

*Project: Lead intake → CRM → welcome email → Telegram alert (n8n)*
*Delivered as: 3 workflow JSON exports + this document. No call required.*

This document is written for the person who will own the automation after delivery. It assumes no prior n8n experience beyond being able to log in.

---

## 1. What was built

Three n8n workflows that together turn a website contact-form submission into a tracked, acknowledged and announced sales lead:

| # | Workflow | Trigger | What it does |
|---|----------|---------|--------------|
| 1 | **Lead Onboarding** | Website form posts to a webhook | Validates and cleans the data, scores the lead, checks the Google Sheet for a duplicate, creates or updates the row, sends the lead a welcome email, posts an alert to the sales Telegram channel, answers the form with `200 OK` (or `400` with the reason if the input was invalid). |
| 2 | **Error Handler** | Any failure in workflow 1 or 3 | Posts the workflow name, failing node, error text and a link to the failed run in Telegram so nothing fails silently. |
| 3 | **Daily Digest** | Every day at 09:00 | Reads yesterday's leads from the sheet, asks an AI model for a short "who to call first" briefing, emails the digest (with a table of all leads) and posts a short version to Telegram. On days with no leads it still sends a one-line heartbeat so you know the automation is alive. |

The Google Sheet is the CRM. Every lead is one row; the sheet is the single source of truth and can be filtered, shared or connected to Looker Studio like any other sheet.

## 2. Where things live

| Thing | Location |
|-------|----------|
| n8n editor | `https://<your-n8n-host>` (owner login was set up during installation) |
| Workflow exports (backup / re-import) | `workflows/*.json` in the delivered repository |
| The CRM sheet | Google Sheet `<name>` — tab **Leads** |
| Webhook the website posts to | `https://<your-n8n-host>/webhook/lead-intake` |
| Sales alerts | Telegram channel `<name>` |
| Error alerts | Telegram channel `<name>` (same or separate) |
| Daily digest | emailed to the address in **Daily Digest → Config → cfg.digestTo** |
| Credentials | n8n → *Credentials* (Google Sheets, SMTP, Telegram, Anthropic/OpenAI). Secrets are stored encrypted inside n8n; they are never in the JSON files. |

## 3. Day-to-day operation

Nothing to do. Leads flow in, rows appear in the sheet, alerts land in Telegram, the digest arrives at 09:00.

**Where to look when someone asks "did we get lead X?"**
1. The sheet — search the `email` column.
2. n8n → *Executions* — every webhook call is listed with its status and the full data at each step.

## 4. Changing common things (no developer needed)

All values you are likely to change are in a single node called **Config** at the start of workflows 1 and 3. Open the workflow, double-click **Config**, edit, click *Save*. Changes apply to the next execution immediately.

| I want to… | Where |
|-----------|-------|
| Change the Telegram channel | **Config → cfg.telegramChatId** (both workflows) and **Error Handler → Telegram: Alert Ops → Chat ID** |
| Change the sender name/address of emails | **Config → cfg.fromEmail** |
| Change who receives the digest | **Daily Digest → Config → cfg.digestTo** |
| Change the digest time | **Daily Digest → Every day at 09:00** node → cron expression (`0 9 * * *` = 09:00; `30 8 * * 1-5` = 08:30 weekdays) |
| Change the welcome-email wording | **Lead Onboarding → Send Welcome Email** → *HTML* field. Everything inside `{{ … }}` is a placeholder filled from the lead; leave those as they are. |
| Change the Telegram message wording | **Telegram: New Lead** / **Telegram: Returning Lead** → *Text* |
| Change what makes a lead "hot" | **Validate & Normalise** (Code node) → the `score` block; the threshold used for the 🔥 emoji is `score >= 60` in the Telegram node |
| Change the AI briefing instructions | **Daily Digest → Summarise with AI** → *Prompt* |
| Use a different sheet | Create it with the same headers (see SETUP.md §3), paste its ID into **Config → cfg.sheetId** in both workflows |
| Also post to Slack | Enable the **Slack** node (right-click → Enable), add a Slack credential, set **Config → cfg.slackChannel** |
| Switch CRM to HubSpot | See README → *Adapting* |

Always click **Save** and keep the workflow **Active** (toggle top-right).

## 5. Things that need a person occasionally

| When | What | How |
|------|------|-----|
| Google OAuth token expires (rare, e.g. after a password change) | Sheet nodes fail with `401` and the Error Handler alerts you | n8n → *Credentials* → Google Sheets → *Reconnect* |
| SMTP provider suspends the sending domain | Welcome emails fail | Check the provider dashboard; the lead is still in the sheet and Telegram alert still fires |
| AI provider key runs out of credit | Digest fails at *Summarise with AI* | Top up or swap the key in *Credentials* |
| n8n update | Optional; do it during a quiet hour | `docker compose pull && docker compose up -d` — workflows and credentials persist in the volumes |
| Backup | Monthly | n8n → workflow → ⋯ → *Download* (or `make export`); also export credentials list. The Postgres volume holds everything if you snapshot the server. |

## 6. Understanding the alerts

**New lead (Telegram):**
```
🆕 New lead — score 80/100 🔥
👤 Jane Doe · ExampleCorp
✉️ jane@examplecorp.com
🌐 source: website
💬 We need a quote for…
✅ Added to CRM · welcome email sent
```
Score is a simple heuristic: business email domain (+40), company given (+25), message longer than 80 characters (+20), mentions budget/quote/pricing/urgent (+15). 60+ gets the 🔥.

**Returning lead:** same contact emailed again. The existing row is updated (`submissions` +1, `last_message`, `status = returning`). No second welcome email is sent.

**Error alert:**
```
🚨 n8n workflow failed
📄 Workflow: Lead Onboarding (id …)
🧩 Node: Send Welcome Email
❌ Error: Invalid login: 535 Authentication failed
🔗 Open execution
```
The link opens the exact failed run with the data at every step. Fix the cause (usually a credential), then in that execution view click *Retry* to re-run it with the same input, so no lead is lost.

## 7. Limits and known behaviour

* The dedupe key is the **email address** (lower-cased). The same person using two addresses creates two rows.
* Google Sheets is comfortable up to roughly 10 000 lead rows. Beyond that move to HubSpot/Postgres (README → *Adapting*), or archive old rows to a second tab.
* The webhook responds only after the sheet, email and Telegram steps finish (typically 2–4 s). If your form needs an instant response, switch the Webhook node's *Respond* option to *Immediately* and delete the two *Respond to Webhook* nodes.
* The AI briefing is generated from the data in the sheet only; the prompt forbids inventing details, but read it as a suggestion, not a fact.
* The daily digest uses the workflow's timezone (*Settings → Timezone*) to decide what "yesterday" means.

## 8. Support

Everything above is reproducible from the repository: `workflows/` (the automation), `docs/SETUP.md` (installation), `tests/` (structural checks run with `make validate`). Re-importing a JSON file restores the workflow to its delivered state; your Config values and credential selections must then be re-entered.
