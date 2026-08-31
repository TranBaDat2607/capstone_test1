# Security policy

## Reporting a vulnerability

Please report security issues **privately** — open a
[GitHub security advisory](https://github.com/TranBaDat2607/capstone_test1/security/advisories/new)
rather than a public issue, so the problem can be fixed before it is described publicly.

Include what you did, what happened, and what you expected. A proof of concept helps; a
working exploit is not required and should not be published.

This is academic capstone software with no production deployment and no paid support, so
there is no formal SLA. Reports are read and acknowledged.

## Secrets and API keys

This project calls paid APIs, so most realistic "security" problems here are leaked
credentials.

- **`.env` is git-ignored and must never be committed.** Copy `.env.example` to `.env` and
  fill in your own keys. `.env.example` contains placeholders only — if a value there ever
  looks like a real credential, that is a bug worth reporting.
- Keys the project reads: `GEMINI_API_KEY` (the default paid provider), `DEEPSEEK_API_KEY`
  and `OPENAI_API_KEY` (both opt-in alternatives), `HF_TOKEN` (private dataset access), and
  `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`.
- **`docker-compose.yml` is for local development only.** It binds Neo4j to localhost and
  takes its password from `${NEO4J_PASSWORD}`. Do not expose that container to a network
  without changing the credentials.
- If you believe a key has been committed anywhere in this repository's history, treat it as
  compromised: **rotate it first**, then report it. Removing it from history does not undo
  the exposure.

## Scope

In scope: credential handling, the API surface in `api/`, dependency vulnerabilities, and
anything that could cause the pipeline to exfiltrate data to an unintended destination.

Out of scope: the accuracy of the system's ESG assessments. The pipeline emits advisory
evidence, not verdicts, and is explicitly not validated against ground-truth greenwashing
labels — see `docs/EVALUATION_BASELINE.md`. Disagreeing with an assessment is a research
question, not a vulnerability.
