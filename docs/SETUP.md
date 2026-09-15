# Setup guide

Step-by-step instructions to get the Lead Onboarding pack running on your own n8n instance. Budget about 45 minutes, most of it spent creating credentials in third-party dashboards.

## 0. What you need

| Item | Where to get it |
|------|-----------------|
| An n8n instance (v1.80+ / 2.x) | `docker compose up -d` in this repo, or n8n Cloud |
| A Google account + a Google Sheet | see step 3 |
| An SMTP account (MailerSend, Postmark, SES, Gmail app password…) | provider dashboard |
| A Telegram bot token + the ID of your sales channel | step 5 |
| An Anthropic or OpenAI API key (digest only) | provider console |
| Optional: HubSpot private-app token, Slack app | only if you enable those nodes |

## 1. Start n8n (self-hosted)

```bash
cp .env.example .env
openssl rand -hex 24          # paste as N8N_ENCRYPTION_KEY
# edit .env: POSTGRES_PASSWORD, N8N_ENCRYPTION_KEY, WEBHOOK_URL (public URL if behind a proxy)
docker compose up -d
open http://localhost:5678    # create the owner account
```

`WEBHOOK_URL` matters: n8n uses it to build the webhook address your website form will POST to. Behind a reverse proxy set it to the public HTTPS address, e.g. `https://n8n.yourdomain.com/`.

## 2. Import the three workflows

**Option A – UI (recommended):** *Workflows → ⋯ → Import from File*, in this order:

1. `workflows/error-handler.json`
2. `workflows/lead-onboarding.json`
3. `workflows/daily-digest.json`

**Option B – CLI (keeps the workflow IDs, so the error-workflow link is preserved):**

```bash
make import
# equivalent to:
# docker compose exec n8n n8n import:workflow --separate --input=/data/workflows
```

The JSON files ship with stable IDs (`lead-onboarding-main`, `lead-onboarding-error-handler`, `lead-onboarding-daily-digest`). With the CLI import the *Error workflow* setting already points at the right workflow. With a UI import n8n assigns new IDs, so after importing open **Lead Onboarding** and **Daily Digest** → *Settings* (⋯ top-right) → *Error workflow* → select **Error Handler – Telegram Alert** → Save.

## 3. Google Sheet (the CRM)

1. Create a new Google Sheet. Rename the first tab to **`Leads`**.
2. Put these headers in row 1, exactly (lower-case, underscores):

   ```
   created_at | created_date | name | email | company | message | source | score | is_business_email | status | submissions | last_seen_at | last_message
   ```
3. Copy the sheet ID from the URL: `https://docs.google.com/spreadsheets/d/`**`<THIS PART>`**`/edit`.
4. In n8n: *Credentials → Add → Google Sheets OAuth2 API*. Follow n8n's guide to create an OAuth client in Google Cloud Console (enable the *Google Sheets API* and *Google Drive API*), paste client ID/secret, click *Sign in with Google*.
5. Open **Lead Onboarding** → **Config** node → set `cfg.sheetId`. Do the same in **Daily Digest → Config**.
6. Open each Google Sheets node (Lookup / Append / Update / Read All Leads) and pick the credential you just created. The document/sheet fields are expressions and need no change.

> A service-account credential works too; share the sheet with the service-account email in that case.

## 4. SMTP credential (welcome email + digest)

*Credentials → Add → SMTP*.

| Provider | Host | Port | User | Password |
|----------|------|------|------|----------|
| MailerSend | `smtp.mailersend.net` | 587 | SMTP username from *Domains → SMTP* | SMTP password |
| Postmark | `smtp.postmarkapp.com` | 587 | Server API token | Server API token |
| Gmail | `smtp.gmail.com` | 465 (SSL) | your address | an *App password* |
| Amazon SES | `email-smtp.<region>.amazonaws.com` | 587 | SMTP user | SMTP password |

Then set `cfg.fromEmail` in both **Config** nodes to an address on a domain that is verified with your provider, e.g. `Sales Team <sales@yourdomain.com>`. Select the credential in **Send Welcome Email** and **Send Digest Email**.

## 5. Telegram bot + channel

1. In Telegram open **@BotFather** → `/newbot` → copy the token.
2. Create a private channel or group for sales alerts and add the bot as an **administrator** (channels) or member (groups).
3. Find the chat ID: post any message in the channel, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read `chat.id` (a negative number such as `-1001234567890`). Alternatively add **@getidsbot** to the group.
4. n8n: *Credentials → Add → Telegram API* → paste the token.
5. Set `cfg.telegramChatId` in both **Config** nodes and the hard-coded `chatId` in **Error Handler → Telegram: Alert Ops** (you may use a different ops channel there). Select the credential in every Telegram node.

## 6. AI credential (daily digest)

*Credentials → Add → Anthropic* (or *OpenAI*) → paste the API key.
Open **Daily Digest → Anthropic Chat Model**, select the credential, then choose a model from the dropdown (the export ships with a placeholder so nothing is hard-coded). To use OpenAI instead: disable the Anthropic node, enable **OpenAI Chat Model (alt)**, drag its round connector onto the **Summarise with AI** node's *Model* input.

## 7. Activate and test

1. Activate **Error Handler** first (toggle top-right). n8n 2.x will not run an inactive error workflow.
2. Activate **Lead Onboarding**. Copy the *Production URL* from the Webhook node, e.g. `https://n8n.yourdomain.com/webhook/lead-intake`.
3. Send a test lead:

   ```bash
   curl -X POST https://n8n.yourdomain.com/webhook/lead-intake \
     -H 'Content-Type: application/json' \
     -d '{"name":"jane doe","email":"jane@examplecorp.com","company":"ExampleCorp","message":"Need a quote for automating our lead pipeline, budget approved."}'
   ```

   Expected: HTTP 200 `{"ok":true,"status":"created",...}`, a new row in the sheet, a welcome email in Jane's inbox, a Telegram post in the sales channel. Send it again → `status: "updated"`, `submissions` = 2, a "returning lead" Telegram post and **no** second welcome email.
4. Send an invalid payload (`{"email":"nope"}`) → HTTP 400 with the validation errors; nothing is written.
5. Activate **Daily Digest**. To test without waiting for 09:00 open it and click *Execute workflow*; it reads yesterday's rows. If there are none you receive the "quiet day" heartbeat email.

## 8. Connect your website form

Point your form at the webhook URL. It accepts `application/json` and `application/x-www-form-urlencoded`; field names `name`, `email`, `company`, `message`, and optionally `source`. Examples:

* **Plain HTML form:** `<form method="POST" action="https://n8n.yourdomain.com/webhook/lead-intake">`
* **Webflow / Framer / Typeform / Tally:** add a webhook integration and map the fields.
* **JavaScript:** `fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)})`.

For production, protect the webhook: open the Webhook node → *Authentication → Header Auth*, create a credential with a secret header, and send that header from your form backend. Also restrict `allowedOrigins` in the node options to your domain.

## 9. Optional nodes

| Node | Enable when | What to configure |
|------|-------------|-------------------|
| **HubSpot: Upsert Contact (alt CRM)** | HubSpot is the system of record | HubSpot *Private App* token credential; then disable the three Google Sheets nodes |
| **Slack: New Lead (optional)** | sales lives in Slack | Slack OAuth2 credential; `cfg.slackChannel` |
| **Slack: Alert Ops (optional)** (error handler) | ops lives in Slack | Slack OAuth2 credential; channel name in node |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Credential with ID "REPLACE_ME" does not exist` | A node still has the placeholder; open it and pick your credential. |
| Webhook returns 404 | Workflow is not active, or you are calling the *test* URL instead of *production*. |
| Sheet lookup always returns "new" | Header must be exactly `email`; check the tab is named `Leads`. |
| Telegram `chat not found` | Bot is not a member/admin of the channel, or chat ID is missing the `-100` prefix. |
| Digest is empty | The sheet's `created_date` must be `YYYY-MM-DD`; the workflow timezone (Settings) must match your business day. |
| Error handler never fires | It must be *active* and selected under *Settings → Error workflow* of the calling workflow. |
