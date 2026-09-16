# Lit-radar

**A literature radar skill for Claude.** Every morning (or once a week) it searches arXiv, bioRxiv, OpenAlex and Europe PMC for papers matching a research profile you write once, deduplicates and prescreens them, has Claude read the evidence and re-score each candidate, and delivers a short, highly selective Markdown report - at most ten papers, zero when nothing clears the bar - with a plain-language explanation of every recommended paper, links to your own projects, reviewer-style caveats, testable research ideas and BibTeX.

The design follows the Codex skill [research-paper-daily-push](https://github.com/TCcjx/research-paper-daily-push) (two-step collect/deliver, evidence review before recommendation, 24 h -> 7 d window expansion, dedup + research memory) and adapts it to Claude's surfaces: **Claude Code**, **Cowork scheduled tasks**, and sandboxes that block direct API access (a WebFetch bridge keeps it working there).

## What a report looks like

`examples/example_report.md` is a full example (fictional papers, real format). Each recommended paper carries:

- a one-line **why you should read it**, addressed to you and your projects;
- a **plain-language paragraph** (80-160 words) for colleagues outside your sub-field - required, validated;
- 3-5 evidence-bound **core findings**;
- **links to your work**, mapped onto the project keys in your profile;
- a **reviewer's eye**: one or two potential weaknesses;
- score breakdown (relevance 0.40 / novelty 0.20 / quality 0.15 / methodology 0.15 / inspiration 0.10), evidence status, tags.

The report closes with a peripheral scan (one line per near-miss), a theme pulse, testable research ideas and a search log.

## How it works

```
collect  (script)  search 4 APIs -> merge & dedup (DOI -> arXiv id -> title) -> transparent prescreen -> drop already-delivered -> review_queue.md
review   (Claude)  read abstracts / open DOIs -> independent 0-100 scores -> reviewed.json (only papers >= 70, max 10)
render   (script)  validate (threshold, evidence status, required fields, plain-language paragraph) -> report.md
deliver  (script)  dedup history + research memory + reports/<date>.md + .bib  (+ optional push)
```

The script does the deterministic work; Claude does the judgement. Prescreen scores only order the queue - recommendations are made after reading.

## Requirements

- Python 3.10+ - standard library only, nothing to install.
- Claude Code, Claude Cowork or claude.ai with a paid plan (skills need code execution).
- Outbound HTTPS to `export.arxiv.org`, `api.biorxiv.org`, `api.openalex.org`, `www.ebi.ac.uk` for direct runs. Sandboxes that block them (Cowork, remote scheduled tasks, claude.ai chat) still work through the WebFetch bridge (`plan` -> WebFetch -> `collect --records`).

## Quick start

```bash
# 1. install as a Claude Code personal skill (or zip the folder and upload it at claude.ai -> Settings -> Skills)
git clone https://github.com/<you>/lit-radar ~/.claude/skills/lit-radar

# 2. offline self-test on bundled fictional records (uses the worked example profile)
python3 ~/.claude/skills/lit-radar/scripts/lit_radar.py selftest --show

# 3. create your work directory with either the blank template or the worked example
python3 ~/.claude/skills/lit-radar/scripts/lit_radar.py init --workdir ~/lit-radar
#   or: ... init --example theoretical-ecology --workdir ~/lit-radar

# 4. fill in config/research_profile.json and config/research_topics.md, set "configured": true
#    (or ask Claude: "Set up lit-radar for me and interview me about my research")

# 5. in Claude Code:  "Run the literature radar (daily), work directory ~/lit-radar"
```

Set `contact_email` in the profile (or `export OPENALEX_MAILTO=you@example.com`): OpenAlex and Crossref give registered "polite pool" clients far higher rate limits.

## Writing your profile

Two files, kept consistent:

- `config/research_profile.json` - machine-readable: boolean queries per source, weighted **topic groups** (strong and weak terms), cross-topic bonuses, watched authors, journal tiers, exclusion terms, your **active projects** (the keys the report links to), scoring thresholds, focus modes.
- `config/research_topics.md` - natural language: who you are, what counts as highly relevant vs peripheral vs unwanted, report taste, who the "outside colleague" for the plain-language paragraphs is.

`references/profile_schema.md` documents every field and the prescreen formula; `config/examples/theoretical-ecology.*` is a complete instance you can copy and cut down.

## Everyday use

| You say | What happens |
|---|---|
| "Run the literature radar" | daily mode: 2-day window, auto-expands to 7 days when quiet |
| "Weekly literature digest" | 7-day window, theme-clustered report |
| "Catch me up, I was away" | 30-day window, still max 10 recommendations |
| "Only --focus &lt;name&gt;" | a focus mode from your profile |
| "Deep-read paper 2" | referee-style analysis of one paper, no new search |
| "Update my profile: ..." | Claude edits both config files consistently |

More copy-paste prompts, including scheduled-task prompts, in `examples/prompts.md`.

## Running it every day

`references/scheduling.md` covers, with trade-offs: Cowork scheduled tasks (zero maintenance, remote - no persistent dedup history unless bound to a local folder), Claude Code Desktop local routines (local files, full history), Claude Code cloud routines (state in a git repository), and cron + `claude -p`.

## Layout

```
lit-radar/
├── SKILL.md                      # operating procedure Claude follows
├── config/
│   ├── research_profile.json     # TEMPLATE (configured: false) - fill in
│   ├── research_topics.md        # TEMPLATE - fill in
│   └── examples/theoretical-ecology.{json,md}   # complete worked example
├── scripts/lit_radar.py          # init | queries | plan | collect | memory | render | deliver | status | selftest
├── references/                   # rubric, report template, schemas, sources, scheduling
├── examples/                     # prompts, example report
└── tests/                        # unittest, offline fixture
```

Runtime data lives in a work directory, never in the skill folder: `WORKDIR/{config,runs/<date>,reports,data}` (`--workdir`, `$LIT_RADAR_HOME`, or `./lit-radar`).

## Tests

```bash
python3 -m unittest discover -s tests -v
python3 scripts/lit_radar.py selftest --show
```

## Privacy

The profile holds research topics only. Credentials (`OPENALEX_MAILTO`, `OPENALEX_API_KEY`, `S2_API_KEY`, push webhooks) are read from environment variables and never written to reports. Reports are generated locally in your work directory; nothing is sent anywhere unless you explicitly use `deliver --push`.

## Contributing

Issues and pull requests are welcome - especially additional worked example profiles for other fields (`config/examples/<field>.json` + `.md`), new sources, and fixes to the source adapters when an API changes. Run the tests before submitting.

## License

MIT - see `LICENSE`.
