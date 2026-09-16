# Literature Radar · 2026-09-16 (Wednesday) · Daily

> Window 2026-09-15 -> 2026-09-16 · Sources: arxiv / biorxiv / openalex / europepmc · Fetched 486 -> deduplicated 431 -> queued 17 -> recommended 3
> WARNING - example report: every paper, author, venue and number below is **fictional** and only illustrates the density and style the real report should have. Produced with the worked example profile (`config/examples/theoretical-ecology.*`); the heading "For a general ecologist" comes from that profile's `plain_summary_label`.

## At a glance

**A preprint carries the storage-effect / relative-nonlinearity partition into a consumer-resource SDE and lands squarely on section 3 of your stochastic-mct manuscript; an Ecology Letters paper gives analytical conditions for when pairwise metrics and feasibility disagree.**

MCT x stochasticity was active today (2 papers), structural stability 1, BEF/BES empirical only, forest-plot work quiet. bioRxiv ecology posted 61 preprints yesterday, none highly relevant.

Top three to read first:
1. **Partitioning invasion growth rates in a stochastic consumer-resource model** - the same model family as your manuscript, with a closed-form weak-noise partition
2. **When pairwise niche and fitness differences disagree with feasibility** - analytical conditions plus 14 empirical communities; your structural-stability manuscript must answer it
3. **Autocorrelated environments erode the portfolio effect** - puts the asynchrony-stability relationship into coloured noise; citable in the BEF/BES manuscript

## ★★★ Must read (score >= 85)

### 1. [Partitioning invasion growth rates in a stochastic consumer-resource model](https://arxiv.org/abs/2609.00001)

- M. Exemplar et al. · arXiv (q-bio.PE) · 2026-09-15 · Preprint · preprint, not peer reviewed
- arXiv:2609.00001
- **Score 90.2** ★★★ · relevance 98 / novelty 85 / quality 82 / methodology 90 / inspiration 88 · evidence: abstract/full text verified · STRONG RECOMMENDATION
- Why strongly recommended: MCT mechanism partitioning in stochastic environments; directly relevant to the stochastic-mct manuscript
- **Why you should read it**: Almost the same two-consumer, one-resource Ito SDE as yours; they obtain closed-form expressions for the storage-effect and relative-nonlinearity terms in the weak-noise limit, where your manuscript currently has only numerics. Either borrow their expansion or show that their i.i.d. environment assumption does not cover your autocorrelated case.
- **For a general ecologist**: Why do two competitors that share one resource sometimes both persist when the environment fluctuates from year to year, rather than the better competitor winning? This preprint takes a small mathematical model of two consumers feeding on one resource, adds random year-to-year environmental variation, and works out (analytically, when the variation is modest) how much each of two classic coexistence mechanisms contributes: the "storage effect", where a species banks the gains of good years while bad years hurt it little, and "relative nonlinearity", where species differ in how they respond to swings in resource abundance. The two mechanisms can push in opposite directions, and in simulations the balance tips as environmental variation grows. The result matters because it tells empiricists which quantities - how species' growth responds to environment and to resource fluctuations - would have to be measured to explain coexistence in variable environments.
- **Core findings**:
  - In the weak-noise limit (sigma -> 0) the storage-effect component Delta_I scales with sigma^2 x Cov(resource response, environment) and the relative-nonlinearity component Delta_N with -sigma^2 x (difference in resource variance) (analytical, section 3)
  - When the two components have opposite signs there is a noise-intensity threshold above which coexistence is governed by Delta_N (numerical, Fig. 4; no analytical threshold given)
  - Quasi-stationary distributions from a numerical Fokker-Planck solution agree with 10^5 Euler-Maruyama simulations (Appendix B)
  - The environment is assumed i.i.d. Gaussian; coloured noise is only mentioned in the Discussion (needs verification whether supplementary material covers it)
- **Links to your work**:
  - [stochastic-mct] Manuscript: two-species consumer-resource SDE and stochastic MCT - the expansion in section 3 can be applied to your autocorrelated-noise case; if your sign result for Delta_N differs from theirs, the Discussion must respond
  - [mct-review] MCT review - citable as the latest reference for "MCT partitions under consumer-resource structure", to be contrasted with Chesson's 2020 partition
- **Reviewer's eye**:
  - No convergence range for the weak-noise expansion is given; the threshold phenomenon in Fig. 4 may lie outside the expansion's validity
  - The Ito vs Stratonovich choice is not stated although the resource equation has multiplicative noise; the partition may depend on it
- **Terms**:
  - **linear noise approximation (LNA)**: a Gaussian approximation obtained by linearising the stochastic process around the deterministic trajectory and scaling the noise by the square root of system size; valid for small noise away from absorbing boundaries
- Needs verification: whether the supplement contains coloured-noise results; the authors' code link (not in the abstract)
- Suggested action: read-full · Tags: #stochastic-LV #SDE #MCT #storage-effect #RNL

### 2. [When pairwise niche and fitness differences disagree with feasibility: analytical conditions and empirical tests](https://doi.org/10.9999/example.0002)

- Q. Placeholder, R. Sample · Ecology Letters · 2026-09-16 · Research article
- DOI [10.9999/example.0002](https://doi.org/10.9999/example.0002)
- **Score 88.6** ★★★ · relevance 96 / novelty 82 / quality 88 / methodology 85 / inspiration 82 · evidence: abstract/full text verified · STRONG RECOMMENDATION
- Why strongly recommended: comparison of pairwise and structural metrics; directly relevant to the structural-stability manuscript
- **Why you should read it**: The direct predecessor of your structural-stability manuscript: they prove that once the interaction matrix is asymmetric beyond a threshold, the rank correlation between pairwise-averaged niche differences and feasibility-domain size vanishes. Your weighted aggregation scheme should be tested on their 14 communities to see whether it repairs the disagreement.
- **For a general ecologist**: Ecologists have two ways of asking whether a set of competing plants can all persist. One works pair by pair: how different are two species' niches, and how unequal are they as competitors? The other looks at the whole community at once and asks how large the set of "safe" conditions is under which every species can persist, given how strongly each species affects each other one. This paper asks when the two answers agree. Using mathematics for three-species communities and data from 14 annual-plant communities, it finds that the answers drift apart as competition becomes lopsided - when species A suppresses B much more than B suppresses A. Nine of the 14 real communities were lopsided enough for this to matter. The practical message is that pairwise measures, which are the ones most field studies collect, can mislead about whole-community coexistence, and the paper proposes a community-level replacement.
- **Core findings**:
  - For three-species LV, the monotonic relationship between pairwise-averaged niche difference and feasibility-domain volume breaks down when ||A - A^T|| / ||A|| > 0.4 (analytical, Theorem 2)
  - 9 of 14 annual-plant communities exceed this threshold (empirical, Table 1)
  - A "structured niche difference" (normalised solid angle of the feasibility domain) is proposed to replace pairwise averaging, but is not compared head-to-head with the Omega metric of Saavedra et al. 2017 (limitation stated by the authors)
- **Links to your work**:
  - [structural-stability] Manuscript: pairwise vs structural niche/fitness-difference metrics - must cite; your weighting scheme can be tested directly on their 14 public interaction matrices; the Discussion needs to position your result relative to their Theorem 2
- **Reviewer's eye**:
  - The 0.4 threshold rests on three-species analysis; the multispecies case is numerical only and the theorem is not shown to generalise
  - The empirical interaction matrices come from neighbourhood regressions; the propagation of estimation error into feasibility volume is not discussed
- Suggested action: replicate · Tags: #structural-stability #feasibility #niche-fitness

## ★★ Worth a look (score 70-84)

### 3. [Autocorrelated environments erode the portfolio effect in competitive communities](https://doi.org/10.9999/example.0003)

- S. Mock et al. · Nature Ecology & Evolution · 2026-09-15 · Research article
- DOI [10.9999/example.0003](https://doi.org/10.9999/example.0003)
- **Score 80.9** ★★ · relevance 85 / novelty 74 / quality 86 / methodology 80 / inspiration 72 · evidence: abstract/full text verified
- **Why you should read it**: Puts the asynchrony-stability relationship into coloured noise: the portfolio effect weakens as the environmental autocorrelation time grows, in the same direction as your bef-bes argument that the structure of stochasticity sets the diversity-stability slope. Citable as theoretical support.
- **For a general ecologist**: Diverse communities are often more stable because different species have good and bad years at different times, so the community total fluctuates less than any single species - the "portfolio effect", by analogy with a diversified investment portfolio. This study asks what happens when the environment itself has memory, so that a warm year is likely to be followed by another warm year. In a competition model with such autocorrelated environments, the stabilising benefit of diversity shrinks as the environment's memory lengthens, because species that respond to the same environmental signal are pushed into synchrony together. Thirty years of grassland monitoring show the expected pattern - species were less asynchronous where environmental autocorrelation was stronger - although this part is correlational. The finding suggests that climate change, which is expected to make some environments more persistent, could weaken one of biodiversity's main stabilising services.
- **Core findings**:
  - In a stochastic LV framework community invariability decreases monotonically with the environmental autocorrelation coefficient rho; at rho = 0.8 the portfolio effect is reduced by about 35% (numerical, Fig. 2)
  - In 30 years of grassland data, between-species asynchrony correlates negatively with observed environmental autocorrelation (correlational, not causal)
  - The theory part is numerical only, no analytical result
- **Links to your work**:
  - [bef-bes] BEF/BES under environmental stochasticity - cite as evidence that noise colour shapes the diversity-stability relationship; an analytical result of yours would fill their gap
- **Reviewer's eye**:
  - The empirical autocorrelation comes from annual precipitation series; rho estimated from 30 points has a wide confidence interval that the abstract does not report
- Suggested action: cite · Tags: #BEF #BES #asynchrony #colored-noise

## Peripheral scan (below the recommendation threshold, one line each)

- [Conspecific negative density dependence across 21 ForestGEO plots](https://doi.org/10.9999/example.0004) · Journal of Ecology · 2026-09-16 - a re-analysis of whether tree seedlings do worse near adults of their own species across 21 large forest plots; no abstract available yet, so it is parked here until it can be re-scored
- [Invasion graphs for Lotka-Volterra systems with higher-order interactions](https://doi.org/10.9999/example.0007) · Journal of Mathematical Biology · 2026-09-14 - extends a mathematical test for whether every species in a community can bounce back from rarity to communities where interactions depend on three or more species at once; pure theory with no ecological example, one step removed from your current manuscripts
- [Soil nutrient heterogeneity and grassland productivity](https://doi.org/10.9999/example.0010) · Oikos · 2026-09-16 - patchier soil nitrogen went with more species coexisting and slightly steadier yields over eight years; observational, no mechanism separated

## Theme pulse

- Stochastic MCT is moving from two-species LV towards consumer-resource structure (1 paper today + 1 last week)
- The structural-stability camp is starting to address when pairwise metrics fail, rather than only proposing replacements
- (continuity) third paper this month on feasibility vs niche-difference disagreement; the 09-03 entry in the research memory used simulated communities, today's has empirical matrices

## Testable research ideas

1. Add AR(1) environmental noise to Exemplar et al.'s weak-noise framework and test whether Delta_I grows linearly with the autocorrelation time - numerically first with your existing SDE pipeline, then attempt an LNA derivation.
   How to test: compare Delta_I / sigma^2 for rho in {0, 0.3, 0.6, 0.9}; nonlinearity would show that their i.i.d. assumption does not extrapolate
   Related: arxiv:2609.00001
2. Test your weighted aggregate niche difference on the 14 interaction matrices published by Placeholder & Sample: if its rank correlation with feasibility volume stays significant above the asymmetry threshold, that is the manuscript's central selling point.
   How to test: Spearman correlation with a permutation test; report the Omega metric as the baseline
   Related: doi:10.9999/example.0002

## Search log

- arxiv: 63 records · ok
- biorxiv: 61 records · ok
- openalex: 318 records · ok
- europepmc: 44 records · ok
- Deduplicated 431 · queued 17 · prescreen high-scoring 5 · dropped as already delivered 3 · preprint-to-published updates 0
- Excluded: exclusion term 4; below queue threshold 396; no topic-group hit 11
- Weights: relevance 0.40 / novelty 0.20 / quality 0.15 / methodology 0.15 / inspiration 0.10 · threshold 70 · ★★★ >= 85 · ★★ >= 70

*lit-radar v1.0.0 · written by Claude after reading the evidence; preprints are not peer reviewed; all numbers should be checked against the original paper.*
