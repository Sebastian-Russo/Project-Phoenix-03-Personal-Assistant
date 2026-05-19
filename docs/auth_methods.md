# Connector Auth Methods — Phoenix 03

## Slack
**Method:** Native REST API — Bot token (xoxb-)
Created a Slack app, added bot scopes, installed to workspace. Bot token
is stable and doesn't expire. Earlier attempt used xoxe configuration
tokens which expire every 12 hours and require rotation — switched to
bot token for reliability.

---

## Google Calendar + Google Drive
**Method:** OAuth2 — shared token file
Single OAuth2 consent flow grants both Calendar and Drive scopes together.
Token stored in `certs/google_token.json` and auto-refreshes on expiry.
Shared `google_auth.py` helper manages credentials for both connectors
so they don't each run separate consent flows.

---

## Spotify
**Method:** OAuth2 Authorization Code flow — manual redirect URL paste
Spotify requires https for redirect URIs which breaks local HTTP server
callback capture. Workaround: browser opens for consent, user pastes
the redirect URL from the address bar into the terminal. Token stored
in `certs/spotify_token.json` and auto-refreshes via refresh token.

---

## GitHub
**Method:** Personal Access Token (PAT)
Generated at github.com → Settings → Developer Settings → Fine-grained tokens.
Included in every request as a Bearer token. No expiry flow needed.
Read-only permissions: Contents, Issues, Pull Requests, Metadata.

---

## Discord
**Method:** Bot token
Created a Discord application and bot user at discord.com/developers.
Bot added to server via OAuth2 URL Generator with bot scope.
Token included in every request as `Authorization: Bot <token>`.
Enabled Message Content Intent and Server Members Intent for full access.

---

## ACRCloud
**Method:** HMAC-SHA1 request signing
Each request is signed with access key + secret using HMAC-SHA1.
No token expiry — credentials are permanent. Identifies songs from
audio files or microphone input against ACRCloud's 100M+ track database.

---

## Jira + Confluence
**Method:** Atlassian API token — Basic auth (email + token)
One token covers both services on the same Atlassian domain.
Generated at id.atlassian.com → Security → API tokens.
Credentials pending — connector built and ready.

---

## Reddit
**Method:** OAuth2 Resource Owner Password flow
Personal script-type app. Username + password sent directly to Reddit's
token endpoint — no browser consent screen needed since the app owner
and account owner are the same person. Approval pending from Reddit.

---

## Summary Table

| Service | Auth Method | Token Expiry | Notes |
|---|---|---|---|
| Slack | Bot token (xoxb-) | Never | Stable, preferred over config tokens |
| Google Calendar | OAuth2 | Auto-refresh | Shared token with Drive |
| Google Drive | OAuth2 | Auto-refresh | Shared token with Calendar |
| Spotify | OAuth2 | 1 hour (auto-refresh) | Manual redirect paste on first run |
| GitHub | Personal Access Token | Never (unless set) | Read-only |
| Discord | Bot token | Never | Requires Message Content Intent |
| ACRCloud | HMAC-SHA1 signing | Never | Per-request signature |
| Jira | Atlassian API token | Never | Pending credentials |
| Confluence | Atlassian API token | Never | Pending credentials |
| Reddit | Password flow | Short-lived + refresh | Pending approval |
