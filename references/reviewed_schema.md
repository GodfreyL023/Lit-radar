# reviewed.json fields

Both `render` and `deliver` read this file. Validation rules live in `scripts/lit_radar.py::validate_reviewed`. Write it to `WORKDIR/runs/<date>/reviewed.json`.

## Root object

```jsonc
{
  "date": "2026-09-16",                 // required; matches runs/<date> (render uses it to find review_queue.json metadata)
  "mode": "daily",                      // daily | weekly | catchup
  "focus": null,                        // focus mode name when --focus was used
  "run_dir": "/abs/path/runs/2026-09-16", // optional; helps render find the meta when directories differ
  "language": "en",
  "term_explanation_mode": "brief",     // brief | dual | none (follows review.term_explanation_mode)
  "summary": {
    "headline": "One sentence: today's most important signal",
    "signal": "1-3 sentences: what the candidate pool says; which directions were active or quiet",
    "top3": [{"title": "Original title", "reason": "why it is first (<= 25 words)"}]
  },
  "articles": [ /* recommendation section, <= max_recommendations, see below */ ],
  "peripheral": [ /* below threshold but worth a glance, <= max_peripheral */
    {"id": "doi:10....", "title": "Original title", "venue": "Oikos", "publication_date": "2026-09-16",
     "url": "https://doi.org/...", "one_liner": "what it did and why it missed the cut, readable by an outside colleague",
     "ecologist_summary": "optional shorter plain-language explanation"}
  ],
  "themes": ["theme clusters in today's candidates, one sentence each"],
  "continuity_notes": ["continuity with the research memory: 'third paper this month on feasibility vs niche differences'"],
  "research_ideas": [
    {"idea": "testable idea (<= 50 words)", "testable_by": "which data / model / derivation would test it", "links": ["doi:..."]}
  ],
  "log": {"fallback": "web_search", "notes": "anything else for the search log"}  // optional; sources/counts are filled from the run meta
}
```

## Each entry of `articles[]`

```jsonc
{
  "id": "doi:10.9999/x",               // copy the id from review_queue (dedup history keys on it)
  "title": "Original title",
  "authors": ["A B", "C D"],            // copied from the queue; used for BibTeX
  "authors_short": "A B et al.",
  "venue": "Ecology Letters",
  "publication_date": "2026-09-16",
  "doi": "10.9999/x",                    // null if none
  "arxiv_id": null,
  "url": "https://doi.org/10.9999/x",
  "article_type": "Research article",   // Research article | Preprint | Review | Methods | Commentary | Data/Software
  "is_preprint": false,
  "peer_reviewed_note": "",              // preprints get "preprint, not peer reviewed" automatically

  "score_status": "evidence_reviewed",   // evidence_reviewed (abstract/full text read) | title_only (never ★★★)
  "component_scores": {"relevance": 92, "novelty": 78, "quality": 85, "methodology": 88, "inspiration": 80},
  // recommendation_score and tier are computed by the script from the weights

  "why_worth_reading": "<= 60 words, addressed to this user, pointing at a specific manuscript or question",
  "ecologist_summary": "REQUIRED. 80-160 words a colleague outside the sub-field can follow: the question, what was done, the qualitative result, why it matters. No equations; unavoidable terms glossed inline; scope stated (e.g. 'in a two-species model').",
  "core_findings": ["3-5 bullets bound to the evidence; numbers exactly as in the paper; 'needs verification' where unsure"],
  "project_links": [{"project": "project-a", "how": "Section 3 gives the condition your project assumes away; compare with your approach"}],
  "reviewer_notes": ["1-2 potential weaknesses: assumptions, identifiability, extrapolation, contradiction with established results"],
  "term_explanations": [               // brief: only methods/concepts the user may not know; dual: every entry needs plain
    {"term": "large deviation principle", "academic": "<= 60-word rigorous definition", "plain": "(required in dual mode) an analogy that keeps the scientific boundary"}
  ],
  "needs_verification": ["abstract does not report the sample size", "DOI page unreachable"],
  "strong_recommendation": false,
  "strong_recommendation_reasons": [],
  "action": "read-full",               // read-full | cite | replicate | skim | contact-author
  "tags": ["tag-one", "tag-two"]   // 1-8, preferably from the profile's tags list
}
```

## What validation rejects

- A paper in `articles` whose recommendation score is below the threshold (default 70) -> move it to `peripheral` or drop it.
- `score_status = title_only` with a recommendation score >= 85.
- Missing `title` / `venue` / `url` / `why_worth_reading` / `core_findings` / `ecologist_summary`, or a `component_scores` object lacking a component.
- An `ecologist_summary` shorter than `review.ecologist_summary_min_chars` (default 200 characters).
- More than `max_recommendations` articles.
- `why_worth_reading` longer than 400 characters (aim for <= 60 words).

## Where `id` comes from

Prefer copying the `id` from `review_queue.json` (`doi:...` / `arxiv:...` / `title:<hash>`). In fallback mode (web search, no queue) the field may be omitted; `deliver` derives it from DOI -> arXiv id -> title hash.
