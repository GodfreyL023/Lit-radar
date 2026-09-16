# Research topics - worked example (theoretical ecology)

> This is the natural-language twin of `theoretical-ecology.json`. Copy both into your work directory with `lit_radar.py init --example theoretical-ecology` and edit, or use them as a model for your own field.

> This file carries the scientific explanation; `research_profile.json` carries the machine-readable search and prescreen rules. Keep them consistent: when one changes, change the other.

## Who the user is and what they work on

A PhD programme at the interface of theoretical ecology and mathematical biology, along three lines:

1. **Modern Coexistence Theory (MCT)**: mechanism partitioning and derivations for the storage effect, relative nonlinearity (RNL) and niche/fitness differences; lottery models; the invasion-growth-rate decomposition (Chesson tradition).
2. **Stability theory**: structural stability (feasibility-domain geometry, Saavedra/Rohr tradition) versus pairwise niche/fitness-difference metrics; permanence theory and invasion graphs (Hofbauer & Schreiber tradition); May-type random-matrix stability.
3. **Stochastic environments**: Ito SDEs, Fokker-Planck equations, linear noise approximation, quasi-stationary distributions; a two-species consumer-resource SDE; coexistence and BEF/BES relationships under autocorrelated environmental noise.

Empirical side: temperate/boreal forest-plot data and ForestGEO large plots; conspecific negative density dependence (CNDD), neighbourhood competition, tree-species coexistence and forest diversity-stability; statistically, integral projection models, the limits of GLMM/GNLMM, hierarchical Bayesian models and time-series fitting.

## Manuscripts in progress (the report's "Links to your work" must map onto these keys)

| key | Content | Most valuable new papers |
|---|---|---|
| `mct-review` | MCT review: storage-effect and lottery-model derivations | new partitioning methods, critiques or corrections of the classical decomposition, synthetic or pedagogical derivations |
| `structural-stability` | pairwise vs structural niche/fitness differences | new metrics, community-level aggregation (weighted averages etc.), comparisons or disagreement cases between the two families of metrics |
| `stochastic-mct` | two-species consumer-resource SDE and stochastic MCT | analytical results for stochastic consumer-resource / LV models, noise colour, extinction times, SDEs combined with MCT |
| `bef-bes` | BEF/BES under environmental stochasticity | new diversity-stability theory, asynchrony/portfolio mechanisms, theory and meta-analyses of BEF in stochastic environments |
| `forest-empirics` | forest-plot / ForestGEO empirics | new methods to estimate coexistence mechanisms or stability from plot data; the CNDD debate; boreal (aspen/spruce mixedwood) dynamics |

## What counts as "highly relevant" (relevance >= 85)

- Directly improves or criticises MCT mechanism partitioning, or extends it to multispecies, spatial, stochastic or consumer-resource settings.
- Theoretical comparison of structural stability / feasibility with niche-fitness metrics; community-level coexistence metrics.
- Analytical or rigorous numerical results for stochastic LV / consumer-resource models (SDEs, Fokker-Planck, large deviations, random matrices).
- New permanence / invasion-graph criteria, especially ones that can be brought to data.
- BEF/BES theory in stochastic environments, or decompositions of asynchrony / portfolio mechanisms.

## What is merely "peripheral" (relevance 40-69)

- General community-ecology empirics without mechanistic partitioning.
- Pure BEF experimental results with no stability or stochasticity dimension.
- Metapopulation / dispersal models unrelated to coexistence.
- Forest ecology unrelated to diversity, coexistence or stability (e.g. pure carbon stocks).

## Explicitly unwanted

- "Coexistence" in the sense of human-wildlife conflict, robotics, wireless spectrum, or social/ethnic contexts.
- Tumour ecology and pure SIR epidemiology (unless the method transfers directly to LV / consumer-resource models).
- Software releases and data-descriptor papers (unless directly about ForestGEO / large plots).

## Report taste

- English throughout; original titles as headings.
- The user is a PhD researcher in this field: do not explain what the storage effect is in the term glossary; reserve `term_explanations` for methods or concepts I may not know (a new statistical method, a stochastic-analysis tool). Mode `brief`.
- **Every recommended paper must carry an ecologist-friendly explanation** (`ecologist_summary`, 80-160 words): a paragraph that a field or empirical ecologist without a mathematics background can follow - the question, what was done, the qualitative result and why it matters - with no equations and any unavoidable term glossed inline. These paragraphs are meant to be forwarded to empirical colleagues and supervisors, so accuracy matters more than flourish.
- Reviewer's eye wanted: for every ★★★/★★ paper give 1-2 potential weaknesses (assumptions too strong, numerics without analysis, sample size, identifiability, contradiction with established results).
- Distinguish direct evidence / correlation / assumption / speculation; preprints must be labelled as not peer reviewed.
- No fabrication: titles, authors, venues, DOIs, numbers, mechanisms; write "needs verification" when the evidence is insufficient.
