# Re-scoring rubric

Recommendation score = 0.40 relevance + 0.20 novelty + 0.15 quality + 0.15 methodology + 0.10 inspiration (each 0-100).
The prescreen score (script) only decides what you read first; the scores below are yours, given after reading the evidence. The bands are generic; `config/research_topics.md` supplies the field-specific meaning of each band (see `config/examples/theoretical-ecology.md` for a filled-in instance).

## relevance (0.40) - against `config/research_topics.md`

| Band | Meaning |
|---|---|
| 90-100 | Directly advances or challenges one of the user's projects in progress: same question, same objects, a result they must build on or answer |
| 75-89 | Same theoretical or methodological body, different object, system or scale; a new tool that plugs straight into a project |
| 55-74 | Adjacent: syntheses of the wider field, empirical work with an explicit frame the user cares about, neighbouring sub-fields |
| 30-54 | Peripheral: general empirics without mechanism, work in the field but without the dimension the user tracks, methods papers with a high transfer cost |
| < 30 | Irrelevant, including non-scientific homonyms of the user's keywords - these should already be excluded by the prescreen |

> Relevance measures usefulness **to this user**, not the paper's general importance. A Nature paper in the wrong sub-field can have relevance 20.

## novelty (0.20)

- 90+: a new mechanism, theorem, metric or dataset type, or a substantive correction of a classical result.
- 70-89: a non-trivial extension of a known framework, or the first bridge between two lines of work.
- 50-69: known methods applied to a new system or dataset; incremental improvement.
- < 50: replication, reviews without a new framework.
- A preprint and its published version are judged on content; preprint status changes neither novelty nor quality by itself.

## quality (0.15)

- Is the chain of evidence closed: assumptions -> derivation/experiment -> results -> conclusions consistent? Are numerics backed by analysis or convergence checks? Data volume and replication?
- Journal tier is only a weak prior (at most +5 for T1). Unknown venues get "needs verification", not an automatic penalty.
- Retractions, corrections, editorials, conference abstracts: never in the recommendation section.
- Title plus truncated abstract only -> quality <= 60 and `score_status = title_only`.

## methodology (0.15)

- Rigour appropriate to the claim (stated assumptions, validity ranges, error propagation, identifiability).
- Computability / applicability: can the method be applied to the user's data or models?
- Reproducibility: code and data available, complete parameter tables.
- Weak methods: numerics without parameter sweeps; black-box models without mechanism; samples too small for the effect claimed.
- `research_topics.md` lists the method signals that matter most to this user; weight them.

## inspiration (0.10)

- Does it generate a concrete next step for this user: a new derivation or analysis target, a prediction testable with their data, an argument to cite or rebut, an experiment or simulation to reproduce?
- Disagreement counts too: a paper whose conclusion contradicts one of the user's projects deserves high inspiration (it must be answered).

## Strong recommendation

`strong_recommendation: true` requires all of: `score_status = evidence_reviewed`, recommendation score >= 85, and every topic group of some rule in `review.strong_recommendation_rules` hit. Put the justification in `strong_recommendation_reasons`.

## The plain-language explanation (`ecologist_summary`)

The field keeps its original name in every discipline; it means "one paragraph for a colleague outside the sub-field" (the profile's `plain_summary_label` sets the heading). Write it after the technical assessment:
1. Open with the question in everyday scientific terms.
2. Say what was done and where the scope ends ("a two-species model solved in the weak-noise limit", "a cohort of 300 patients followed for two years").
3. State the result qualitatively and gloss any unavoidable term inline.
4. Close with why it matters for how people in the field think about the problem.
Faithfulness beats flourish: no numbers the paper does not give, no mechanisms it does not test. 80-160 words.

## Reviewer's-eye dimensions (reviewer_notes)

1. Assumptions too strong: linearisation, limiting regimes, small-case results extrapolated, independence assumptions.
2. Numerics only: no analysis, no sensitivity, no replicate runs.
3. Identifiability: quantities treated as known that cannot be estimated from the data used.
4. Scale or population mismatch between model and data.
5. Conflicts with established results left unexplained.
6. Data: sample size, series length, missing-value handling, dependence structure.

## "Deep-read paper N" checklist (no new search)

1. Open the full text (WebFetch the DOI / arXiv PDF); capture the setup: model or design, assumption list, parameter or sample ranges.
2. Restate the main results as 2-3 testable propositions; mark which are proven, which are numerical or empirical observations.
3. Map the results onto the user's own framework and vocabulary.
4. Locate conflicts with the user's projects: assumptions, conclusions, metrics.
5. Output in referee format (Major / Minor / Worth borrowing) and end with "cite or not, and in which section".
