"""Offline unit tests: python3 -m unittest discover -s tests -v  (run from the skill root)"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import lit_radar as lr  # noqa: E402

EXAMPLE = ROOT / "config" / "examples" / "theoretical-ecology.json"
PROFILE = json.loads(EXAMPLE.read_text(encoding="utf-8"))
TEMPLATE = json.loads((ROOT / "config" / "research_profile.json").read_text(encoding="utf-8"))
FIXTURE = ROOT / "tests" / "fixtures" / "sample_records.json"


class TermMatching(unittest.TestCase):
    def test_multiword_and_dash_variants(self):
        t = "partitioning the storage effect and relative nonlinearity in a stochastic consumer–resource model"
        self.assertEqual(lr._term_hits(t, ["storage effect", "relative nonlinearity", "consumer-resource"]),
                         ["storage effect", "relative nonlinearity", "consumer-resource"])

    def test_plural_and_boundaries(self):
        self.assertEqual(lr._term_hits("niche and fitness differences matter", ["fitness difference"]), ["fitness difference"])
        self.assertEqual(lr._term_hits("the biocoexistence gene", ["coexistence"]), [])  # no match inside a word

    def test_variant_dedup(self):
        self.assertEqual(lr._term_hits("a fokker-planck analysis", ["fokker planck", "fokker-planck"]), ["fokker planck"])


class Template(unittest.TestCase):
    def test_template_is_unconfigured_and_refuses(self):
        self.assertFalse(TEMPLATE["configured"])
        problems = lr.validate_profile(TEMPLATE)
        self.assertTrue(any("configured" in p for p in problems))

    def test_example_is_valid(self):
        self.assertEqual(lr.validate_profile(PROFILE), [])
        self.assertEqual(PROFILE.get("contact_email", ""), "")


class Normalisation(unittest.TestCase):
    def test_norm_doi(self):
        self.assertEqual(lr.norm_doi("https://doi.org/10.1111/ELE.14000"), "10.1111/ele.14000")
        self.assertEqual(lr.norm_doi("doi:10.1/abc"), "10.1/abc")
        self.assertIsNone(lr.norm_doi(""))

    def test_parse_date(self):
        self.assertEqual(str(lr.parse_date("2026-09-05T10:00:00Z")), "2026-09-05")
        self.assertEqual(str(lr.parse_date([[2026, 9]])), "2026-09-01")
        self.assertIsNone(lr.parse_date("n/a"))


class Merging(unittest.TestCase):
    def test_merge_by_title_and_doi(self):
        fx = json.loads(FIXTURE.read_text(encoding="utf-8"))["records"]
        merged = lr.merge_records(fx)
        self.assertEqual(len(merged), len(fx) - 1)  # the arXiv and OpenAlex copies of one preprint are merged
        rec = next(r for r in merged if r.get("arxiv_id") == "2609.00001")
        self.assertEqual(rec["doi"], "10.9999/demo.0001")  # DOI filled in from the other copy
        self.assertTrue(rec["abstract"])  # the copy with an abstract wins
        self.assertEqual(sorted(rec["sources"]), ["arxiv", "openalex"])


class Prescreen(unittest.TestCase):
    def _score(self, title, abstract="", venue="", authors=()):
        rec = {"title": title, "abstract": abstract, "venue": venue, "authors": list(authors)}
        return lr.prescreen(rec, PROFILE)

    def test_core_title_hit_is_high(self):
        r = self._score("Relative nonlinearity and the storage effect in fluctuating environments")
        self.assertGreaterEqual(r["score"], 70)
        self.assertIn("MCT core", r["hits"])

    def test_exclusion(self):
        r = self._score("Human-wildlife coexistence in cities", "coyotes and people")
        self.assertTrue(r["excluded"])
        r2 = self._score("Coexistence of Wi-Fi and 5G", "spectrum sharing")
        self.assertTrue(r2["excluded"])

    def test_weak_only_hit_is_low(self):
        r = self._score("Seed dispersal distances of a palm", "dispersal kernels were estimated")
        self.assertFalse(r["excluded"])
        self.assertLess(r["score"], PROFILE["prescreen"]["queue_min_score"])

    def test_bonuses(self):
        r = self._score("Structural stability of niche and fitness differences", "feasibility domain", venue="Ecology Letters",
                        authors=["Serguei Saavedra", "Someone Else"])
        self.assertEqual(r["journal_tier"], 1)
        self.assertIn("Serguei Saavedra", r["author_hits"])
        self.assertTrue(any("cross-topic" in b for b in r["bonuses"]))

    def test_author_variants(self):
        self.assertEqual(lr._author_hits(["Chesson P", "X Y"], PROFILE["author_watchlist"]), ["Peter Chesson"])
        self.assertEqual(lr._author_hits(["Wang S"], PROFILE["author_watchlist"]), [])  # surname + initial alone must not match (false positives)

    def test_no_hit_excluded(self):
        r = self._score("A new species of beetle from Borneo", "taxonomy")
        self.assertEqual(r["excluded"], "no topic-group hit")


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lr-test-"))

    def _collect(self, **kw):
        ns = dict(workdir=str(self.tmp), profile=str(EXAMPLE), mode="daily", days=None, since=None, until=None, focus=None, topic=None,
                  offline=str(FIXTURE), min_score=None, max_queue=None, include_seen=False, tag=None)
        ns.update(kw)
        import argparse
        rc = lr.cmd_collect(argparse.Namespace(**ns))
        self.assertEqual(rc, 0)
        run_dir = self.tmp / "runs" / lr.today().isoformat()
        return json.loads((run_dir / "review_queue.json").read_text(encoding="utf-8"))

    def test_collect_queue_and_exclusions(self):
        rq = self._collect()
        titles = [c["title"] for c in rq["candidates"]]
        self.assertTrue(any("structural stability" in t.lower() for t in titles))
        self.assertFalse(any("wi-fi" in t.lower() for t in titles))
        self.assertEqual(rq["meta"]["excluded_reasons"].get("exclusion term"), 2)
        self.assertTrue((self.tmp / "runs" / lr.today().isoformat() / "review_queue.md").exists())

    def test_focus_mode_reweights(self):
        rq_all = self._collect()
        rq_bef = self._collect(focus="bef")
        s_all = {c["id"]: c["prescreen"]["score"] for c in rq_all["candidates"]}
        s_bef = {c["id"]: c["prescreen"]["score"] for c in rq_bef["candidates"]}
        perm = "doi:10.9999/demo.0007"  # a pure permanence paper should score lower under the bef focus
        self.assertLess(s_bef.get(perm, 0), s_all[perm])

    def test_reviewed_validation_and_render_and_deliver(self):
        rq = self._collect()
        cand = rq["candidates"][0]
        good = {
            "date": lr.today().isoformat(), "mode": "daily",
            "articles": [{
                "id": cand["id"], "title": cand["title"], "venue": cand["venue"], "url": cand["url"], "doi": cand.get("doi"),
                "publication_date": cand["published_date"], "is_preprint": cand["is_preprint"], "authors": cand["authors"],
                "score_status": "evidence_reviewed",
                "component_scores": {"relevance": 92, "novelty": 80, "quality": 85, "methodology": 85, "inspiration": 80},
                "why_worth_reading": "Test reason.", "core_findings": ["finding 1", "finding 2", "finding 3"],
                "ecologist_summary": "x" * 220,
                "project_links": [{"project": "structural-stability", "how": "directly relevant"}], "tags": ["structural-stability"],
            }],
            "peripheral": [{"id": rq["candidates"][-1]["id"], "title": rq["candidates"][-1]["title"], "url": "https://x", "venue": "V", "one_liner": "one line"}],
        }
        self.assertEqual(lr.validate_reviewed(good, PROFILE), [])
        self.assertAlmostEqual(good["articles"][0]["recommendation_score"], 86.3, places=1)
        md = lr.render_report(good, PROFILE, rq["meta"])
        for needle in ("# Literature Radar", "★★★ Must read", "Links to your work", "For a general ecologist", "Peripheral scan", "Search log", cand["title"]):
            self.assertIn(needle, md)

        # a below-threshold article must be caught by validation
        bad = json.loads(json.dumps(good))
        bad["articles"][0]["component_scores"] = {"relevance": 60, "novelty": 60, "quality": 60, "methodology": 60, "inspiration": 60}
        self.assertTrue(any("below the threshold" in p for p in lr.validate_reviewed(bad, PROFILE)))
        # a missing ecologist_summary must be caught
        bad3 = json.loads(json.dumps(good))
        bad3["articles"][0].pop("ecologist_summary")
        self.assertTrue(any("ecologist_summary" in p for p in lr.validate_reviewed(bad3, PROFILE)))
        # title_only cannot get three stars
        bad2 = json.loads(json.dumps(good))
        bad2["articles"][0]["score_status"] = "title_only"
        self.assertTrue(any("title_only" in p for p in lr.validate_reviewed(bad2, PROFILE)))

        # deliver -> seen / memory / bib
        import argparse
        rv_path = self.tmp / "reviewed.json"
        rv_path.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
        rc = lr.cmd_deliver(argparse.Namespace(workdir=str(self.tmp), profile=str(EXAMPLE), reviewed=str(rv_path), report=None,
                                               bibtex=True, push="none", no_memory=False))
        self.assertEqual(rc, 0)
        seen = json.loads((self.tmp / "data" / "seen_papers.json").read_text(encoding="utf-8"))
        self.assertIn(cand["id"], seen["papers"])
        self.assertEqual(len(seen["papers"]), 2)
        mem = json.loads((self.tmp / "data" / "research_memory.json").read_text(encoding="utf-8"))
        self.assertEqual(mem["project_counts"]["structural-stability"], 1)
        bib = (self.tmp / "reports").glob("*.bib")
        self.assertTrue(list(bib))
        # a second collect must drop the delivered papers
        rq2 = self._collect()
        self.assertNotIn(cand["id"], [c["id"] for c in rq2["candidates"]])
        self.assertEqual(rq2["meta"]["counts"]["dropped_seen"], 2)
        # memory context is readable
        self.assertIn("Research memory", lr.memory_context(mem))

    def test_bridge_records_normalised(self):
        recs = {"bridge": True, "records": [
            {"title": "Storage effects in a stochastic consumer-resource model", "authors": "Ada Test; Bo Test", "venue": "arXiv",
             "published_date": "2026-09-15T00:00:00Z", "arxiv_id": "2609.01234v1", "source": "arxiv"},
            {"title": "Storage effects in a stochastic consumer\u2013resource model", "doi": "https://doi.org/10.9999/bridge.2", "source": "europepmc"},
        ], "failed": {"biorxiv": "truncated"}}
        path = self.tmp / "bridge.json"
        path.write_text(json.dumps(recs), encoding="utf-8")
        import argparse
        ns = argparse.Namespace(workdir=str(self.tmp), profile=str(EXAMPLE), mode="daily", days=None, since=None, until=None, focus=None, topic=None,
                                offline=None, records=str(path), min_score=None, max_queue=None, include_seen=False, tag=None)
        self.assertEqual(lr.cmd_collect(ns), 0)
        rq = json.loads((self.tmp / "runs" / lr.today().isoformat() / "review_queue.json").read_text(encoding="utf-8"))
        self.assertEqual(rq["meta"]["fetch_mode"], "bridge")
        self.assertEqual(rq["meta"]["counts"]["merged"], 1)  # dash variant merged
        rec = rq["candidates"][0]
        self.assertEqual(rec["arxiv_id"], "2609.01234")
        self.assertEqual(rec["doi"], "10.9999/bridge.2")
        self.assertEqual(rec["authors"], ["Ada Test", "Bo Test"])
        self.assertEqual(rec["published_date"], "2026-09-15")
        self.assertTrue(rq["meta"]["sources"]["biorxiv"]["status"].startswith("failed"))
        self.assertIn("WebFetch bridge", (self.tmp / "runs" / lr.today().isoformat() / "review_queue.md").read_text(encoding="utf-8"))

    def test_plan_urls(self):
        urls = lr.bridge_urls(PROFILE, lr.dt.date(2026, 9, 15), lr.dt.date(2026, 9, 16), None, None, 25)
        srcs = {u["source"] for u in urls}
        self.assertEqual(srcs, {"arxiv", "biorxiv", "openalex", "europepmc"})
        self.assertTrue(all(u["url"].startswith("https://") for u in urls))

    def test_bibtex(self):
        b = lr.bibtex_for({"title": "Storage effects everywhere", "authors": ["Ada B. Case", "Bo Fixture"], "venue": "Ecology",
                           "publication_date": "2026-09-01", "doi": "10.9999/x", "url": "https://doi.org/10.9999/x"})
        self.assertTrue(b.startswith("@article{case2026storage,"))
        self.assertIn("Ada B. Case and Bo Fixture", b)


if __name__ == "__main__":
    unittest.main()
