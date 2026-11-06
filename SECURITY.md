# Security

## Reporting

Report suspected vulnerabilities privately to the project maintainer rather than in a public issue.

## What is implemented

| Area | Implementation | Tested |
|---|---|---|
| Passwords | Argon2id, 10 character minimum, timing-equalised login | Yes |
| Sessions | Random token in an HttpOnly, SameSite=Lax cookie; only its SHA-256 is stored; revoked on password change or reset | Yes |
| CSRF | Per-session token required in a header on every mutating request | Yes |
| Authorisation | Membership and role checked in the backend on every request; other workspaces' objects return 404 | Yes |
| SQL injection | SQLAlchemy parameters everywhere; sort columns are allow-listed | Yes |
| XSS | React escaping, no raw HTML rendering, strict CSP | CSP header tested |
| Security headers | CSP, HSTS in production, nosniff, frame deny, referrer and permissions policies | Yes |
| Credentials | Fernet-encrypted at rest; only masked previews leave the server; workflows hold a reference | Yes |
| Secrets in workflows | Saving is refused when a config contains a literal auth header or a recognisable key format | Yes |
| Secrets in logs | Sensitive keys redacted, and the actual credential values used in a run are scrubbed from logs, including a value echoed back by a remote server | Yes |
| SSRF | See below | Yes |
| Webhooks | HMAC SHA-256 with a 5 minute timestamp window, or a secret token; 1 MB body limit; rate limit per endpoint; secret shown once | Yes |
| Rate limiting | Login, registration, password reset, AI, runs, node tests, webhooks | Yes |
| Code execution | None. Transforms are declarative and expressions are parsed, not evaluated | Yes |
| Regex | Third-party `regex` engine with hard timeouts, to prevent ReDoS | Partly |
| Resource limits | Execution time, node count, loop iterations, delay length, response size, record size, queue depth | Yes |
| AI | Backend only. Proposals pass the validator, cannot set credentials, are never activated or run automatically. Node inputs are marked as untrusted data | Yes |
| Audit log | Sign-ins, credential, workflow, member, webhook and live-test actions | Yes |

### SSRF protection

The HTTP and webhook nodes:

1. Allow only `http` and `https`, and refuse credentials in URLs.
2. Refuse internal hostnames and IP literals.
3. Resolve the hostname and refuse if **any** address is loopback, private, link-local, carrier-grade NAT, reserved, multicast or a cloud metadata endpoint. IPv4-mapped, 6to4, Teredo and NAT64 forms are unwrapped.
4. **Pin the connection to the validated IP**, while keeping Host, SNI and certificate checks on the hostname, to defeat DNS rebinding. This was also verified against a real HTTPS site.
5. Follow redirects manually, validating every hop, and drop auth headers when the host changes.
6. Cap the response size and time.

`ALLOW_PRIVATE_HTTP_HOSTS` is a narrow development exception and is ignored when `APP_ENV=production`.

## Dependency checks

Run `pip-audit -r backend/requirements.txt` and `npm audit --omit=dev`. Both reported no known vulnerabilities at release.

## Deployment checklist

- [ ] `APP_ENV=production`. The app refuses to start without an encryption key and `COOKIE_SECURE=true`, or with demo mode on
- [ ] Serve only over HTTPS through a reverse proxy
- [ ] Run uvicorn with `--proxy-headers` and restrict `--forwarded-allow-ips` to your proxy, so rate limits see real client addresses
- [ ] Use PostgreSQL with a dedicated, least-privilege user
- [ ] Store `CREDENTIALS_ENCRYPTION_KEY` in a secret manager and back it up
- [ ] Block egress to internal networks at the firewall as a second layer of SSRF defence
- [ ] Add a mail provider before relying on password reset
- [ ] Set `PUBLIC_BASE_URL` so webhook URLs are correct

## Known limitations

- **The demo account is public and shared** when `DEMO_MODE_ENABLED=true`. Anyone can edit its workflows, and its HTTP node makes outbound requests from your server. That is why production refuses it. Do not expose a demo-enabled instance to the internet.
- **Webhook replay:** a captured signed request can be replayed within the 5 minute window. There is no nonce store.
- **SMTP connections** check the host against the SSRF rules but are not IP-pinned, so a DNS-rebinding attack on that path is not fully closed. Egress filtering covers it.
- **Trigger data is stored as received**, so retries can use it. Sensitive keys are redacted when it is returned by the API or written to logs, but database access reveals it. Secrets under innocuous key names cannot be detected.
- **Rate limits are in-process** and reset on restart.
- **Key rotation:** there is no tool yet to re-encrypt credentials under a new key.
- **Prompt injection:** content passed to AI nodes can still influence their text output. The nodes have no tools and their results are data, so keep a condition or a person between AI output and consequential actions.
- **No third-party penetration test** has been done.
