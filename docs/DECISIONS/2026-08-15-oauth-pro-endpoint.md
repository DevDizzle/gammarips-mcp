# 2026-08-15: OAuth 2.1 on the MCP, the `/pro` endpoint

Status: DECIDED by the owner 2026-08-15 ("we do not wait, we do it now in
anticipation"). Built 2026-08-19. This note is the MCP-repo half of the
decision. The authorization server lives in `gammarips-webapp`
(`src/lib/oauth/`, `src/app/oauth/`, `src/app/.well-known/`). The engine plan
is `gammarips-engine/docs/GTM-ORGANIC-GROWTH-PLAN.md` item D4.

## Decision

1. gammarips.com is the **authorization server** (issuer
   `https://gammarips.com`). It signs RS256 access tokens with a `tier`
   claim read from the subscription, rotates refresh tokens, supports
   Client ID Metadata Documents, dynamic registration, PKCE S256, and a
   `client_credentials` grant for **machine clients** a subscriber creates
   on `/account`.
2. The MCP is a **resource server only**. It verifies tokens against the
   issuer JWKS. It stores no OAuth state and writes nothing, so the
   read-only trust model in `SECURITY.md` holds.
3. `/pro` is the auth-required endpoint. A request with no valid
   credential gets `401` + the RFC 9728 discovery header. That is the
   trigger a chat client needs to start the OAuth flow. `/mcp` stays
   anonymous, so the free funnel does not change.
4. API keys keep working on both endpoints. A JWT works everywhere a key
   works. Tiering, metering, and the denial envelope are identical for both.
5. A valid token with `tier=free` is admitted to `/pro`. The pro tools
   answer with the `subscription_required` envelope, which now tells OAuth
   clients that pro applies on the next token refresh (within one hour)
   after they subscribe.

## Why

- ChatGPT cannot send API keys at all, and claude.ai only in a slow beta.
  A paying chat-client user could not use the paid tools. OAuth is the one
  lever that turns "how to trade options with ChatGPT" into a page that
  ends in a purchase. Measured first: 30 days of logs showed 0 ChatGPT and
  0 claude.ai paywall hits; the build is a forecast bet on the Robinhood
  agentic wave, not a demand response.
- The owner also wants the headless VM agent (real capital, live-agent
  lane) on a short-lived credential with the subscription re-checked on
  every mint. That is the machine client. An API key is still the simplest
  path for `claude -p` and stays supported.

## What was built (2026-08-19)

- `src/utils/oauth.py`: JWKS cache with a one-minute refetch cooldown,
  `verify_access_token` (RS256 only, iss, aud ∈ our resource URIs, 60s
  leeway, sub required), `ProEndpointMiddleware` (pure ASGI, 401 +
  `WWW-Authenticate`, path rewrite `/pro` → `/mcp`, identity handed down),
  protected-resource metadata (root + path forms), an issuer-checked mirror
  of the AS metadata, master switch `OAUTH_ENABLED`.
- `src/utils/auth.py`: `Identity.client_class` / `client_id`, the JWT branch
  in `resolve_identity`, the meter fields, identity reuse from the gateway.
- `src/server.py`: middleware order CORS → RateLimit → ProEndpoint →
  AccessGate → RequestLogger; discovery routes; server card `authentication.oauth`;
  `SERVER_VERSION` 4.2.0.
- Tests: `tests/test_oauth_pro.py` (offline, preloaded JWKS). Webapp
  `scripts/oauth/e2e.ts` drove the REAL MCP SDK client through DCR, Claude
  Code's CIMD document, `client_credentials`, a free-tier user, deny, a bad
  redirect, and the discovery documents against a local AS + local MCP:
  24/24 passed.

## Rollout

1. Webapp PR merges (main auto-deploys) after `/ship`. Needs the signing
   key in Secret Manager (`OAUTH_SIGNING_KEY`, granted to the App Hosting
   backend) and `OAUTH_SIGNING_KID` in `apphosting.yaml`.
2. MCP deploy via `scripts/deploy.sh` (`gammarips-review` gate first).
   `OAUTH_ENABLED` defaults to true; ship with `OAUTH_ENABLED=false` if the
   webapp is not live yet and flip with
   `gcloud run services update gammarips-mcp --update-env-vars OAUTH_ENABLED=true`.
3. Verify live: `curl -i https://mcp.gammarips.com/pro` → 401 with
   `WWW-Authenticate`; `curl https://gammarips.com/.well-known/oauth-authorization-server`;
   add `https://mcp.gammarips.com/pro` in Claude Code and authenticate.
4. Weekly read: `MCP_TOOL_CALL` by `client_class` and `client_id`.

## Consequences

- Two credential kinds share one tiering code path. A change to
  `tool_allowed` or the denial envelope applies to both.
- Access tokens live one hour. A subscription lapse reaches an OAuth client
  within an hour (refresh re-checks), which is looser than the 120s key
  cache but inside the two-day `proUntil` grace the webapp already grants.
- The run.app hostnames are accepted audiences so a client that connects
  through them still works; `mcp.gammarips.com/pro` is the canonical
  resource the AS defaults to.
- `/pro` admits free-tier tokens. This is deliberate: a 401 there would put
  a non-subscriber's client into an authorization loop. The envelope does
  the selling.
- The AS metadata mirror on the MCP host is a convenience for old clients
  and is never edited by hand.

## Known residual (found 2026-08-19 during the prod e2e): 127.0.0.1 loopback redirects

The App Hosting edge (Google Front End) rewrites the literal token `127.0.0.1`
inside a query parameter before the request reaches the Next.js route, an
SSRF-style normalization. Effect on the authorization server:

- A `redirect_uri` whose host is the literal `127.0.0.1` fails the redirect
  match on **production** (400 "Invalid redirect_uri"), even when it exactly
  equals the registered value.
- The SAME request passes on local dev (identical code + prod Firestore), and
  passes on prod when the `redirect_uri` is omitted (the route uses the stored
  value) or when the host dots are percent-encoded (`127%2E0%2E0%2E1`). So the
  webapp code is correct; the platform mangles the incoming query token.
- `localhost`, `https`, and private-use scheme redirects are unaffected (all
  302). The prod e2e is green end to end using `localhost`.

Impact: low. Chat clients use `https` (ChatGPT, claude.ai, Cursor) or bind
`localhost` (Claude Code, whose CIMD document registers both `localhost` and
`127.0.0.1`). A native client that uses ONLY a `127.0.0.1` loopback would 400.

Guidance: developer copy should tell native clients to use `localhost` as the
loopback host, not `127.0.0.1`. A code-side mitigation is not reliable (the
value is already altered before the route runs); the real fix, if a client
ever needs it, is an App Hosting / Cloud Armor rule exception, which is an
owner + infra change. Not a launch blocker.
