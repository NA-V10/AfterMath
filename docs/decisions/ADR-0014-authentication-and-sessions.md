# ADR-0014: Bearer-token authentication, scrypt passwords, roles re-read per request

- **Status:** Accepted (Phase 5)
- **Date:** 2026-11-22

## Context

The governance model in [SECURITY.md](../SECURITY.md) §3 needs authenticated users with roles: viewer, operator, approver and admin. The owner decided on two points:

- Every screen requires sign-in, not only actions that change state.
- Demo accounts take their password from the git-ignored `.env`.

The Phase 0 design named JWT and argon2. On the development host, however, Windows Application Control blocks some native extension modules. In Phase 5 it blocked import-linter's compiled module, so the argon2 binding is likely to be blocked too.

## Decision

**Passwords**
- Passwords are hashed with standard-library **scrypt** (N=2¹⁴, r=8, p=1, 16-byte salt). This needs no native dependency.
- Verification is constant-time.
- An unknown username still costs one hash, so response timing does not reveal which usernames exist.

**Tokens**
- Tokens are **HS256 JWTs** issued with **PyJWT**, a small pure-Python library and the only new dependency.
- They carry `sub`, `roles`, `iss`, `aud`, `iat` and `exp`.
- Decoding accepts only HS256 and requires every one of those claims.
- The default lifetime is 8 hours (`JWT_TTL_MINUTES`).

**Authorisation**
- The token proves only the username. **The account's roles and active flag are re-read from the database on every request**, so deactivating or demoting a user takes effect immediately.
- Roles are cumulative: viewer < operator < approver < admin.
- The decision logic lives in pure `governance.rules.policies`.

**Scope**
- Every `/api/v1` route needs a token except `/health`, `/health/ready` and `/auth/token`.
- This is enforced by a viewer-level dependency on each router.
- A test calls every operation in the OpenAPI document without a token and expects 401.

**Browser session**
- The token is kept in `sessionStorage`: one tab, cleared when the tab closes. It is not kept in a cookie, so there is no CSRF exposure.
- The workflow progress stream uses `fetch` streaming instead of `EventSource`, so it can send the `Authorization` header. Tokens are never placed in URLs.

**Secrets**
- `JWT_SECRET` and `DEMO_PASSWORD` come from the environment.
- An empty `JWT_SECRET` falls back to a development placeholder.
- **The API refuses to start in production** if the secret is that placeholder, is shorter than 32 characters, or the database URL still uses the placeholder password.

## Consequences

- (+) No new native code. Revocation by deactivating the account is immediate. Every route is covered by a test.
- (+) Separation of duties can be enforced reliably, because the server always knows who is acting.
- (−) There is one extra database query per request to load the user. That is negligible at this scale.
- (−) There is no refresh token: a session ends after the TTL and the user signs in again.
- (−) `sessionStorage` is readable by scripts on the page. An XSS flaw could therefore steal a token. React escaping and the absence of `dangerouslySetInnerHTML` are the mitigations.
- (−) scrypt instead of argon2. Both are memory-hard and acceptable under OWASP guidance. Switching later only needs a new prefix in the hash format.

## Alternatives considered

- **Cookie sessions.** No token is visible to scripts, but they need CSRF protection and are awkward with the separate API origin used in development.
- **argon2-cffi.** Blocked native code is a likely failure on this host.
- **Hand-written HMAC tokens.** Rejected: don't write your own token format.
