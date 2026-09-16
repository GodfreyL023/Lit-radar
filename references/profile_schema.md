# `research_profile.json`: fields and tuning

Run `python3 scripts/lit_radar.py init --workdir WORKDIR` (blank template) or `init --example theoretical-ecology --workdir WORKDIR` (complete worked example) to copy the configuration into the work directory, then edit it there. The template ships with `configured: false` and refuses to search until filled in. After editing, run `collect --offline tests/fixtures/sample_records.json --workdir /tmp/x` to confirm the JSON is valid. `research_topics.md` is the natural-language twin of the same research direction; change both together.

## Required

| Field | Meaning |
|---|---|
| `profile_name` | short name written into the run metadata |
| `configured` | must be `true` before any search runs; set it back to `false` and clear the topics before sharing the profile publicly |
| `research_context` | 2-4 sentences of background that Claude reads when judging relevance |
| `queries.openalex` / `queries.europepmc` | boolean query strings (`AND / OR / NOT`, phrases in quotes). **No commas** (OpenAlex separates filters with commas). Each query is a separate request; 5-10 queries is a good range |
| `topic_groups[]` | topic groups for the deterministic prescreen: `label`, `weight` (1-100), `terms` (strong terms), optional `weak_terms` (generic words counted at `prescreen.weak_multiplier`) |

## Optional

| Field | Meaning |
|---|---|
| `active_projects[]` | `key` / `label` / `keywords`. "Links to your work" in the report must map onto these keys; update them when projects change |
| `priority_questions[]` | the core scientific questions Claude checks candidates against |
| `queries.crossref` / `queries.semantic_scholar` | both sources are off by default; Crossref ignores boolean syntax, so use simple phrases |
| `arxiv.categories` | fetched by category and scored locally (keywords are not pushed into the arXiv query, so differently worded papers are not missed). `max_results_per_category` defaults to 200 |
| `biorxiv.categories` | lower-case category names such as `ecology`, `evolutionary biology` |
| `sources` | per-source on/off switches |
| `window` | `default_days` (2), `expand_to_days` (7), `min_high_score_candidates` (3; fewer triggers the expansion), `weekly_days`, `catchup_days` |
| `cross_topic_bonuses[]` | add `bonus` when every listed label has a strong-term hit; expresses "the intersection of these two lines is what matters most" |
| `author_watchlist[]` | `name` plus optional `variants`. Full-name permutations are matched automatically; "surname + initial" forms (`Chesson P`) must be listed explicitly under `variants`, and should be avoided for common surnames (Wang S, He F) because of false positives |
| `journal_tiers` | `tier_1/2/3` venue names (case and punctuation insensitive); a weak prior only |
| `exclusion_terms[]` | a hit excludes the record, unless a core group (weight >= 90) also hits in the title, in which case 40 points are subtracted instead. Keep it conservative |
| `prescreen` | see below |
| `review` | `recommendation_threshold` (70), `max_recommendations` (10), `weights`, `tiers`, `language` (`en`), `term_explanation_mode` (brief/dual/none), `ecologist_summary_words` ("80-160", guidance for Claude), `plain_summary_label` (heading shown before the plain-language paragraph, e.g. "For a general ecologist" or "For a clinician"), `ecologist_summary_min_chars` (200, enforced by validation; the field keeps its historical name in every discipline), `max_peripheral`, `strong_recommendation_rules` |
| `focus_modes` | named focus modes: `groups` (focus groups; the rest are weighted x0.4) and optional per-source `queries` overrides |
| `tags` | preferred tag vocabulary |
| `delivery` | `report_dir`, `bibtex` (default true), `push` (informational; actual pushing is `deliver --push`) |
| `contact_email` | used as `mailto` for OpenAlex/Crossref (polite pool, more stable); alternatively the `OPENALEX_MAILTO` environment variable |

## How the prescreen score is computed (`prescreen`)

```
raw = sum over groups of weight x (title hit 1.0 | abstract-only 0.5) x (1 + 0.1 x extra strong terms, max +0.3)
    + sum over groups of weight x weak_multiplier (0.35) x (title 1.0 | abstract 0.5)    # weak terms
    + cross-topic bonuses + journal tier (T1 10 / T2 6 / T3 3) + watched author 15 - missing abstract 5
score = 100 x (1 - exp(-raw / saturation (80)))
```

- `queue_min_score` (30): threshold to enter the review queue. Too much noise -> 35-40; missing relevant papers -> 25.
- `high_score` (70): what counts as a "high-scoring candidate" when deciding whether to expand the window.
- `max_queue` (60): queue cap; use `--max-queue 120` for weekly runs.
- `abstract_chars` (1200): abstract truncation length in review_queue.md.

## Common tuning situations

- **Zero recommendations every day**: check the search log first - source failure or empty queue? If the queue is empty, lower `queue_min_score`, promote words from `weak_terms` to `terms`, or add `queries`.
- **Too much noise**: move generic words to `weak_terms`, extend `exclusion_terms`, lower the weight of broad groups.
- **Pause a direction**: lower that group's `weight` to 20-30 instead of deleting it (keeps the history traceable).
- **New project**: update `active_projects` and the project table in `research_topics.md`; adjust `cross_topic_bonuses` reasons.
- **Longer or shorter plain-language summaries**: change `review.ecologist_summary_words` (guidance) and `ecologist_summary_min_chars` (validation) together.
