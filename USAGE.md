# Usage guide

## 0. How it works in 30 seconds

```
You say "Run the literature radar"
   │
   ▼
① script `collect`: queries arXiv / bioRxiv / OpenAlex / Europe PMC for the last 2 days (auto-expands to 7 when quiet)
   → merges & deduplicates → prescreens against your topic groups → drops papers already delivered → runs/<date>/review_queue.md
   │
   ▼
② Claude reviews: reads every abstract in the queue (opens the DOI page when the abstract is missing), scores each paper
   independently against research_topics.md → keeps only papers >= 70 with solid evidence (max 10) → writes reviewed.json
   (each paper: why you should read it, a plain-language paragraph, core findings, links to your projects, reviewer's eye ...)
   │
   ▼
③ script `render`: validates (below-threshold papers, title-only three-star ratings, missing fields, missing or short
   plain-language paragraphs are all rejected) → report.md
   │
   ▼
④ Claude shows you the report
   │
   ▼
⑤ script `deliver`: dedup history (no repeats tomorrow), research memory, reports/lit-radar_<date>.md and .bib
```

The script does the deterministic work (search, dedup, scoring, validation, bookkeeping); Claude does the judgement (reading evidence, scoring, writing). Prescreen scores only order the queue.

## 1. Install

### A. Claude Code (recommended for daily use and local scheduling)

```bash
mkdir -p ~/.claude/skills
cp -r lit-radar ~/.claude/skills/lit-radar        # personal skill, available in every project
# or:  cp -r lit-radar <repo>/.claude/skills/lit-radar   # project skill
```

Type `/lit-radar` or just say "run the literature radar".

### B. claude.ai web / desktop / mobile (including Cowork)

1. Zip the folder (`zip -r lit-radar.zip lit-radar`) and upload it at **Settings -> Features (or Customize) -> Skills -> Upload skill**. Requires Pro/Max/Team/Enterprise with code execution enabled.
2. Switch the skill on. Cowork sessions and Cowork scheduled tasks load the skills enabled for your account.
3. Say "Run today's literature radar with lit-radar". The claude.ai chat sandbox and the Cowork sandbox block direct API calls (HTTP 403); Claude then uses the WebFetch bridge (see §7) - same pipeline, slightly smaller coverage.

### C. Both

Claude Code for local runs and scheduling, an uploaded copy for Cowork and mobile. Keep the two configuration copies in sync by hand; the dedup histories are separate.

## 2. First run: write your profile

```bash
S=~/.claude/skills/lit-radar/scripts/lit_radar.py

python3 $S selftest --show                  # offline: runs the whole pipeline on fictional records with the worked example profile
python3 $S init --workdir ~/lit-radar       # copies the blank template into your work directory
#   or start from the complete theoretical-ecology example and cut it down:
python3 $S init --example theoretical-ecology --workdir ~/lit-radar
```

Then edit `~/lit-radar/config/research_profile.json` and `research_topics.md`:

1. `research_context` - 2-4 sentences on what you work on.
2. `active_projects` - 2-6 projects with short keys; the report's "Links to your work" maps onto these keys.
3. `queries.openalex` / `queries.europepmc` - 5-10 boolean strings (`AND / OR`, phrases in quotes, **no commas**).
4. `topic_groups` - 4-9 weighted groups; put specific multi-word phrases in `terms`, generic words in `weak_terms`.
5. `arxiv.categories`, `biorxiv.categories`, `journal_tiers`, `exclusion_terms`, `author_watchlist`.
6. `contact_email` - your address, used as OpenAlex/Crossref `mailto` (much higher rate limits). Alternatively `export OPENALEX_MAILTO=you@example.com`.
7. Mirror the same content in `research_topics.md` (what is highly relevant, peripheral, unwanted; who the "outside colleague" for the plain-language paragraphs is; `review.plain_summary_label` sets that paragraph's heading).
8. Set `"configured": true`. The skill refuses to search before that.

You can also let Claude do it: *"Set up lit-radar for me and interview me about my research."* Every field is documented in `references/profile_schema.md`.

Check the configuration without network:

```bash
python3 $S collect --offline ~/.claude/skills/lit-radar/tests/fixtures/sample_records.json --workdir /tmp/lr-check
python3 $S queries --workdir ~/lit-radar      # print the queries that will be sent
python3 $S collect --mode daily --workdir ~/lit-radar   # a real search; look at runs/<date>/review_queue.md
python3 $S status --workdir ~/lit-radar
```

Tip: `export LIT_RADAR_HOME=~/lit-radar` in your shell profile, then you never have to mention the work directory.

## 3. Everyday phrases

| You want | Say |
|---|---|
| daily report | "Run the literature radar" / "any new papers today?" |
| weekly | "Weekly literature digest" |
| catch up | "I was away two weeks, catch me up (catchup mode)" |
| one direction only | "--focus <name>" (names under `focus_modes` in your profile) |
| an extra topic today | "Add one topic: <phrase> AND <topic>" |
| deep read | "Deep-read paper 2, referee format" |
| longer plain-language paragraphs | "Make the plain-language explanations about 150 words today" |
| citations | `.bib` is exported by `deliver` automatically |
| change direction | "Update my profile: lower <group>, add project <key>" |

More in `examples/prompts.md`.

## 4. Run it every day

See `references/scheduling.md` for details. Shortest paths:

- **Cowork** (zero maintenance): Scheduled -> New task -> paste the "Cowork scheduled-task prompt" from `examples/prompts.md` -> Daily. Remote runs keep no dedup history (the date window avoids most repeats); binding a local folder keeps history but needs your computer on.
- **Claude Code Desktop** (local, full history): Code tab -> Routines -> New routine -> Local -> choose `~/lit-radar` -> paste the prompt -> daily -> on the first Run now choose "always allow".
- **cron**: `claude -p "Use the lit-radar skill ..." --allowedTools "Bash(python3 *),Read,Write,Edit,WebFetch,WebSearch" --permission-mode acceptEdits` (script in scheduling.md).

## 5. Where things live

```
~/lit-radar/
├── config/research_profile.json, research_topics.md   # your configuration
├── runs/2026-09-16/review_queue.md                    # today's candidates (browse it yourself)
├── runs/2026-09-16/reviewed.json, report.md           # Claude's review and the report
├── reports/lit-radar_2026-09-16.md, .bib              # archive (after deliver)
└── data/seen_papers.json, research_memory.json        # dedup history, research memory
```

Reset the dedup history by deleting `data/seen_papers.json`; let one paper reappear by removing its id from that file.

## 6. Tuning

- **Zero recommendations every day?** Check the Search log at the end of the report: sources failed, or queue empty? If empty, lower `prescreen.queue_min_score`, promote words from `weak_terms` to `terms`, add queries. Low-output fields legitimately have many zero days; weekly mode is richer.
- **Irrelevant papers recommended?** Move generic words to `weak_terms`, add `exclusion_terms`, lower the weight of broad groups.
- **The same paper reappears after a few days?** OpenAlex indexing lag puts old papers into the window; once delivered it will not come back. Remote Cowork tasks have no persistent history - expected.
- **HTTP 429 from OpenAlex?** Set `contact_email` / `OPENALEX_MAILTO`; reduce the number of queries; lower `window.min_high_score_candidates` so the 7-day expansion fires less often.

## 7. When the sandbox blocks the APIs (Cowork, claude.ai chat, remote scheduled tasks)

Symptom: `collect` fails for every source with HTTP 403 (`X-Proxy-Error: blocked-by-allowlist`). The sandbox routes shell traffic through a proxy with a fixed allowlist; this is a policy denial, not an outage.

Fixes, most reliable first:

1. **Run outside the sandbox**: Claude Code Desktop local routine, the Claude Code CLI, or cron + `claude -p`.
2. **WebFetch bridge** (works inside the sandbox): `lit_radar.py plan` writes small-page API URLs plus an extraction prompt; Claude fetches each with WebFetch (not routed through the proxy), saves the records to `bridge_records.json`, and `collect --records` takes over. The scheduled-task prompts in `examples/prompts.md` already allow this.
3. **Allowlist the hosts**: claude.ai -> Settings -> Capabilities -> Code execution and file creation -> Allow network egress -> Additional allowed domains: `export.arxiv.org`, `api.biorxiv.org`, `api.openalex.org`, `www.ebi.ac.uk` (Team/Enterprise: an admin, under Organization -> Capabilities). Restart the app and start a new session. Users have reported the allowlist being ignored in Cowork; treat this as a bonus.

## 8. Other questions

- **Report in another language?** Ask for it ("write today's report in French"); structure and technical terms stay the same. Default is English.
- **Can't see the report file in claude.ai?** The work directory must be `/mnt/user-data/outputs/lit-radar`; Claude presents the file.
- **Push to Slack / WeCom / ServerChan?** Set `LIT_RADAR_WEBHOOK_URL`, `WECOM_WEBHOOK_URL` or `SERVERCHAN_SENDKEY` and authorise `--push` explicitly in the prompt.
