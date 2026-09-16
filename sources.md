# Data sources

All sources are public academic APIs that need no key; the script uses `urllib` only. A failing source does not stop the others; its status is written to `review_queue.json -> meta.sources`.

| Source | Endpoint | Coverage | Default | Notes |
|---|---|---|---|---|
| arXiv | `https://export.arxiv.org/api/query` (Atom) | new submissions in the categories listed under `arxiv.categories` (example profile: q-bio.PE, math.DS, nlin.AO, physics.bio-ph, cond-mat.stat-mech, q-bio.QM) | on | fetched by category and `submittedDate` range, then scored locally. 3 s between requests (arXiv's rule). `max_results_per_category` 200 |
| bioRxiv | `https://api.biorxiv.org/details/biorxiv/{from}/{to}/{cursor}` | every preprint in the date range, filtered to the categories under `biorxiv.categories` | on | 100 per page, cursor pagination. The `published` field gives the journal DOI (used for the preprint-to-published flag). EcoEvoRxiv has no stable API; OpenAlex covers it |
| OpenAlex | `https://api.openalex.org/works` | the main journal source for any field (works of every venue OpenAlex indexes) | on | `filter=from_publication_date,to_publication_date,title_and_abstract.search:<boolean string>`; the abstract is rebuilt from `abstract_inverted_index`; anonymous limit 10 req/s and 100k/day; set `contact_email` or `OPENALEX_MAILTO` to join the polite pool; optional `OPENALEX_API_KEY`. **Indexing lags 1-7 days**, which is why the default window is 2 days plus dedup history |
| Europe PMC | `https://www.ebi.ac.uk/europepmc/webservices/rest/search` | PubMed-indexed journals plus preprints (`SRC:PPR`); strong for life sciences and medicine | on | `resultType=core` includes abstracts; `FIRST_PDATE:[from TO to]`; cursorMark pagination |
| Crossref | `https://api.crossref.org/works` | publisher metadata, abstracts often missing | off | `query.bibliographic` is not boolean-aware; use simple phrases. `mailto` joins the polite pool |
| Semantic Scholar | `https://api.semanticscholar.org/graph/v1/paper/search` | good abstracts and TL;DRs | off | strict anonymous rate limit (frequent 429); enable after setting `S2_API_KEY` |

## Date semantics

- Most academic APIs only have day resolution, so "the last 24 hours" is approximate; the report states the actual window.
- OpenAlex `publication_date` is often the Early View date; the same paper may appear first as a preprint (bioRxiv/arXiv) and weeks later as the journal version - the script merges both by normalised title and marks the journal version as an update in the dedup history.
- Auto-expansion: in daily mode, when fewer than `min_high_score_candidates` high-scoring candidates are found, the window expands to `expand_to_days` (7); an explicit `--since/--days` disables expansion.

## Common failures

| Symptom | Handling |
|---|---|
| arXiv returns an empty Atom feed or 503 | occasional on the official API; the script retries twice; if it still fails the log says failed and the other sources continue |
| OpenAlex 403/429 | set `contact_email`; reduce the number of `queries`; make sure no query contains a comma |
| bioRxiv timeout | many records in the range (Mondays often > 500); the script pages at most 30 times |
| Europe PMC returns 0 | unbalanced parentheses in a boolean string; print and check with the `queries` subcommand |
| Everything fails with 403 (exit code 2) | the sandbox proxy blocks the hosts (`X-Proxy-Error: blocked-by-allowlist`). See "Sandbox egress" below, then use SKILL.md §7 Fallback A (WebFetch bridge via `plan`) |
| A long queue of irrelevant papers | tune per `profile_schema.md`: weak terms, exclusion terms, `queue_min_score` |

## Sandbox egress (Cowork, remote scheduled tasks, claude.ai chat)

Bash commands inside these sandboxes reach the internet only through a proxy with a domain allowlist; anything else returns `HTTP 403 Forbidden`, often with `X-Proxy-Error: blocked-by-allowlist`. That is a policy denial, not an outage - retrying will not help.

Ways around it, most reliable first:
1. **Run outside the sandbox**: Claude Code Desktop local routine, Claude Code CLI, or cron + `claude -p` on your own machine call the APIs directly.
2. **WebFetch bridge** (any sandbox that has the WebFetch tool): `lit_radar.py plan` writes small-page API URLs; Claude fetches them with WebFetch (which is not routed through the sandbox proxy) and hands the records to `collect --records`. Coverage is somewhat smaller (25-record pages, OpenAlex without abstracts) but scoring, dedup and history all work normally.
3. **Allowlist the hosts** (personal accounts: claude.ai -> Settings -> Capabilities -> "Code execution and file creation" -> "Allow network egress" -> Domain allowlist -> add `export.arxiv.org`, `api.biorxiv.org`, `api.openalex.org`, `www.ebi.ac.uk` (and `api.crossref.org`, `api.semanticscholar.org` if enabled) under "Additional allowed domains"; Team/Enterprise: an admin does it under Organization -> Capabilities). Restart the desktop app and start a new session. As of September 2026 several users report the allowlist not being applied inside Cowork sessions, and remote scheduled agents have no self-serve allowlist at all - so treat this as a bonus, not the plan.

## Web-search hints for Fallback B

- Queries (examples from the worked profile): `"storage effect" 2026 arXiv`, `"structural stability" coexistence 2026`, `site:biorxiv.org ecology coexistence`, `"Ecology Letters" early view coexistence`; `lit_radar.py queries` prints the ones derived from your own profile.
- Keep only the last 7 days; confirm at least title, authors, venue, date and link for every paper; without an abstract use `score_status: title_only`.
- Set `log.fallback` to `web_search` in reviewed.json so the report shows that coverage is incomplete.

## Your own credentials

Read from environment variables only: `OPENALEX_MAILTO`, `OPENALEX_API_KEY`, `S2_API_KEY`, and for pushing `WECOM_WEBHOOK_URL`, `SERVERCHAN_SENDKEY`, `LIT_RADAR_WEBHOOK_URL`. Never write them into the profile or a report.
