# Security Policy

## Reporting a vulnerability

Please do not report security vulnerabilities in public Issues, Discussions,
pull requests, or other public channels.

Use GitHub's private vulnerability reporting workflow:

[Report a vulnerability privately](https://github.com/Qredence/fleet-agent/security/advisories/new)

If private reporting is unavailable, email [contact@qredence.ai](mailto:contact@qredence.ai)
with the subject line `[fleet-agent security]`. Do not include secrets or
live user data in an initial report. The mailbox must be treated as a private
security-reporting channel by the project maintainers.

Please include, when safe to share:

- The affected commit, release, or deployment.
- A concise description of the impact and attack scenario.
- Reproduction steps or a minimal proof of concept.
- Affected configuration, endpoint, or component.
- Any suggested mitigation.

Maintainers will coordinate acknowledgement, remediation, and disclosure with
the reporter. Please allow time for a fix and coordinated disclosure before
publishing technical details.

## Supported versions

Fleet Agent is pre-release software and does not currently maintain supported
release branches. Reports should target the latest `main` commit and include
the exact commit SHA or version used. A future release policy will be added
when stable releases are published.

## Current security boundaries and limitations

- The current application uses a single local owner for projects and threads;
  it is not a multi-user authorization system.
- `FLEET_AGENT_API_KEY` is a shared API credential, not per-user identity.
- `VITE_API_KEY` is embedded in browser assets and must not be treated as a
  secret.
- The default local artifact storage and development PostgreSQL configuration
  are intended for local use, not direct untrusted production exposure.
- Raw DSPy reasoning, provider prompts, stack traces, and unredacted tool
  payloads must remain server-side.
- Exact CORS origins, request-size limits, timeouts, concurrency limits, and
  safe public error codes are part of the application hardening boundary.

For general setup or a non-sensitive bug, use [SUPPORT.md](SUPPORT.md) and the
appropriate public project channel instead.
