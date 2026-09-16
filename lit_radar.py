#!/usr/bin/env python3
"""lit_radar.py - literature radar CLI bundled with the lit-radar Claude skill.

Python standard library only; nothing to pip install.

Subcommands:
  init      copy the default configuration into the work directory so it can be edited there
  queries   print the search plan (per-source queries plus a web-search fallback for sandboxes without network)
  collect   query arXiv / bioRxiv / OpenAlex / Europe PMC (optionally Crossref / Semantic Scholar),
            merge and deduplicate, prescreen, drop previously delivered papers, write runs/<date>/review_queue.{json,md}
  memory    print recent research memory (read it before reviewing so ideas are not repeated)
  render    turn the reviewed.json written by Claude into the Markdown report (offline, with validation)
  deliver   record delivery: save the report under reports/, export BibTeX, update dedup history and research memory, optional push
  status    show work directory, last run, history counts
  selftest  run the whole pipeline offline on bundled fictional records

Work directory resolution: --workdir > $LIT_RADAR_HOME > ./lit-radar
Profile resolution:        --profile > <workdir>/config/research_profile.json > <skill>/config/research_profile.json
The bundled config/research_profile.json is an unfilled template (configured: false); `init --example theoretical-ecology`
copies a complete worked example instead, and `init` alone copies the template for you to fill in.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = SKILL_DIR / "config" / "research_profile.json"
DEFAULT_TOPICS = SKILL_DIR / "config" / "research_topics.md"
EXAMPLES_DIR = SKILL_DIR / "config" / "examples"
EXAMPLE_PROFILE = EXAMPLES_DIR / "theoretical-ecology.json"  # used by selftest/tests when the template is unconfigured
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "sample_records.json"

REVIEW_WEIGHTS = {"relevance": 0.40, "novelty": 0.20, "quality": 0.15, "methodology": 0.15, "inspiration": 0.10}


# ----------------------------------------------------------------------------
# Basic helpers
# ----------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def today() -> dt.date:
    return dt.date.today()


def parse_date(value: Any) -> dt.date | None:
    """Accept YYYY-MM-DD / YYYY-MM / YYYY / ISO timestamps / Crossref date-parts."""
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    if isinstance(value, list):  # Crossref date-parts: [[2026, 9, 15]]
        try:
            parts = value[0] if value and isinstance(value[0], list) else value
            y = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 and parts[1] else 1
            d = int(parts[2]) if len(parts) > 2 and parts[2] else 1
            return dt.date(y, m, d)
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2) or 1), int(m.group(3) or 1)
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def norm_title(title: str) -> str:
    t = html.unescape(title or "").lower()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", t)
    return " ".join(t.split())[:160]


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = str(doi).strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"^doi:\s*", "", d)
    return d or None


def strip_tags(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<jats:title>.*?</jats:title>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def truncate(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def canonical_id(rec: dict) -> str:
    if rec.get("doi"):
        return "doi:" + rec["doi"]
    if rec.get("arxiv_id"):
        return "arxiv:" + rec["arxiv_id"]
    return "title:" + hashlib.sha1(norm_title(rec.get("title", "")).encode()).hexdigest()[:16]


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}")


def http_get(url: str, headers: dict | None = None, timeout: int = 30, retries: int = 2, backoff: float = 2.0) -> bytes:
    hdrs = {"User-Agent": f"lit-radar/{VERSION} (Claude skill; stdlib urllib)", "Accept": "application/json, application/atom+xml;q=0.9, */*;q=0.5"}
    if headers:
        hdrs.update(headers)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = backoff * (attempt + 1)
                if exc.code == 429:  # rate limited: honour Retry-After, otherwise back off harder
                    ra = exc.headers.get("Retry-After") if exc.headers else None
                    wait = float(ra) if ra and ra.isdigit() else max(wait, 8.0 * (attempt + 1))
                time.sleep(min(wait, 60.0))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            raise
    raise RuntimeError(str(last_exc))


def http_json(url: str, **kw) -> Any:
    return json.loads(http_get(url, **kw).decode("utf-8", errors="replace"))


# ----------------------------------------------------------------------------
# Paths and configuration
# ----------------------------------------------------------------------------

def resolve_workdir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    env = os.environ.get("LIT_RADAR_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / "lit-radar").resolve()


def resolve_profile_path(workdir: Path, arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    local = workdir / "config" / "research_profile.json"
    return local if local.exists() else DEFAULT_PROFILE


def resolve_topics_path(workdir: Path) -> Path:
    local = workdir / "config" / "research_topics.md"
    return local if local.exists() else DEFAULT_TOPICS


def load_profile(path: Path) -> dict:
    prof = load_json(path, None)
    if prof is None:
        raise SystemExit(f"Research profile not found: {path}")
    problems = validate_profile(prof)
    if problems:
        raise SystemExit("Research profile incomplete; refusing to search (topics must not be invented):\n  - " + "\n  - ".join(problems))
    return prof


def validate_profile(prof: dict) -> list[str]:
    problems = []
    if not prof.get("configured"):
        problems.append("configured is not true: fill in the research topics first, then set configured to true")
    if not prof.get("research_context"):
        problems.append("research_context is missing")
    groups = prof.get("topic_groups") or []
    if not groups:
        problems.append("at least one topic_groups entry is required")
    for g in groups:
        if not g.get("label") or not g.get("terms") or not (1 <= int(g.get("weight", 0)) <= 100):
            problems.append(f"invalid topic_group {g.get('label')!r} (needs label, weight 1-100, non-empty terms)")
    q = prof.get("queries") or {}
    if not any(q.get(k) for k in ("openalex", "europepmc", "crossref", "semantic_scholar")):
        problems.append("queries needs at least one openalex/europepmc query")
    return problems


# ----------------------------------------------------------------------------
# Sources: each fetcher returns a list of records in a common shape
# Common fields:
#   title, abstract, authors[list[str]], venue, venue_type(journal|preprint|other), type,
#   published_date(YYYY-MM-DD), doi, arxiv_id, url, pdf_url, peer_reviewed(bool), is_preprint(bool),
#   published_doi (journal DOI of a preprint, when known), sources[list], categories[list]
# ----------------------------------------------------------------------------

def _mailto(prof: dict) -> str:
    return os.environ.get("OPENALEX_MAILTO") or prof.get("contact_email") or ""


def fetch_arxiv(prof: dict, d_from: dt.date, d_to: dt.date) -> list[dict]:
    cfg = prof.get("arxiv", {})
    cats = cfg.get("categories") or ["q-bio.PE"]
    max_results = int(cfg.get("max_results_per_category", 200))
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    out: dict[str, dict] = {}
    span = f"[{d_from.strftime('%Y%m%d')}0000 TO {d_to.strftime('%Y%m%d')}2359]"
    for i, cat in enumerate(cats):
        if i:
            time.sleep(3.0)  # arXiv API politeness delay
        q = f"cat:{cat} AND submittedDate:{span}"
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": max_results}
        )
        root = ET.fromstring(http_get(url, headers={"Accept": "application/atom+xml"}))
        for e in root.findall("a:entry", ns):
            raw_id = (e.findtext("a:id", default="", namespaces=ns) or "").strip()
            m = re.search(r"arxiv\.org/abs/([^v\s]+)(v\d+)?", raw_id)
            if not m:
                continue
            aid = m.group(1)
            published = parse_date(e.findtext("a:published", default="", namespaces=ns))
            updated = parse_date(e.findtext("a:updated", default="", namespaces=ns))
            is_new = published == updated or updated is None
            title = " ".join((e.findtext("a:title", default="", namespaces=ns) or "").split())
            abstract = " ".join((e.findtext("a:summary", default="", namespaces=ns) or "").split())
            authors = [" ".join((a.findtext("a:name", default="", namespaces=ns) or "").split()) for a in e.findall("a:author", ns)]
            categories = [t.get("term", "") for t in e.findall("a:category", ns)]
            primary = e.find("arxiv:primary_category", ns)
            pcat = primary.get("term") if primary is not None else (categories[0] if categories else cat)
            doi = norm_doi(e.findtext("arxiv:doi", default="", namespaces=ns))
            pdf = ""
            for l in e.findall("a:link", ns):
                if l.get("title") == "pdf":
                    pdf = l.get("href", "")
            rec = {
                "title": title, "abstract": abstract, "authors": authors,
                "venue": f"arXiv ({pcat})", "venue_type": "preprint", "type": "preprint",
                "published_date": published.isoformat() if published else "",
                "doi": doi, "arxiv_id": aid, "url": f"https://arxiv.org/abs/{aid}", "pdf_url": pdf,
                "peer_reviewed": False, "is_preprint": True, "published_doi": doi,
                "sources": ["arxiv"], "categories": categories, "is_new_version": is_new,
                "journal_ref": (e.findtext("arxiv:journal_ref", default="", namespaces=ns) or "").strip(),
            }
            out[aid] = rec
    return list(out.values())


def fetch_biorxiv(prof: dict, d_from: dt.date, d_to: dt.date) -> list[dict]:
    cfg = prof.get("biorxiv", {})
    wanted = {c.lower() for c in (cfg.get("categories") or ["ecology"])}
    server = cfg.get("server", "biorxiv")
    out: dict[str, dict] = {}
    cursor, pages = 0, 0
    while pages < 30:
        url = f"https://api.biorxiv.org/details/{server}/{d_from.isoformat()}/{d_to.isoformat()}/{cursor}"
        data = http_json(url)
        coll = data.get("collection") or []
        msg = (data.get("messages") or [{}])[0]
        for it in coll:
            if (it.get("category") or "").lower() not in wanted:
                continue
            doi = norm_doi(it.get("doi"))
            if not doi:
                continue
            prev = out.get(doi)
            if prev and int(prev.get("version", 1)) >= int(it.get("version", 1) or 1):
                continue
            pub = it.get("published")
            pub_doi = norm_doi(pub) if pub and pub != "NA" else None
            out[doi] = {
                "title": " ".join((it.get("title") or "").split()),
                "abstract": " ".join(strip_tags(it.get("abstract") or "").split()),
                "authors": [a.strip() for a in (it.get("authors") or "").split(";") if a.strip()],
                "venue": f"{server} ({it.get('category')})", "venue_type": "preprint", "type": "preprint",
                "published_date": it.get("date", ""), "doi": doi, "arxiv_id": None,
                "url": f"https://www.biorxiv.org/content/{doi}v{it.get('version', 1)}",
                "pdf_url": f"https://www.biorxiv.org/content/{doi}v{it.get('version', 1)}.full.pdf",
                "peer_reviewed": False, "is_preprint": True, "published_doi": pub_doi,
                "sources": ["biorxiv"], "categories": [it.get("category", "")], "version": it.get("version", 1),
                "is_new_version": str(it.get("version", "1")) == "1",
            }
        total = int(msg.get("total", 0) or 0)
        count = int(msg.get("count", len(coll)) or 0)
        cursor += count if count else 100
        pages += 1
        if not coll or cursor >= total:
            break
    return list(out.values())


def _openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            pos.append((i, word))
    pos.sort()
    return " ".join(w for _, w in pos)


def fetch_openalex(prof: dict, d_from: dt.date, d_to: dt.date, queries: list[str]) -> list[dict]:
    out: dict[str, dict] = {}
    params_base = {
        "per-page": 100, "sort": "publication_date:desc",
        "select": "id,doi,title,display_name,publication_date,type,primary_location,authorships,abstract_inverted_index,ids",
    }
    mailto = _mailto(prof)
    api_key = os.environ.get("OPENALEX_API_KEY")
    for q in queries:
        for page in range(1, 4):
            flt = f"from_publication_date:{d_from.isoformat()},to_publication_date:{d_to.isoformat()},title_and_abstract.search:{q}"
            params = dict(params_base, filter=flt, page=page)
            if mailto:
                params["mailto"] = mailto
            if api_key:
                params["api_key"] = api_key
            url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
            data = http_json(url)
            results = data.get("results") or []
            for w in results:
                doi = norm_doi(w.get("doi"))
                key = doi or ("oa:" + (w.get("id") or ""))
                if key in out:
                    continue
                loc = w.get("primary_location") or {}
                src = (loc.get("source") or {})
                venue = src.get("display_name") or ""
                wtype = w.get("type") or ""
                is_pre = wtype == "preprint" or (src.get("type") == "repository")
                authors = []
                for a in w.get("authorships") or []:
                    nm = (a.get("author") or {}).get("display_name")
                    if nm:
                        authors.append(nm)
                out[key] = {
                    "title": w.get("title") or w.get("display_name") or "",
                    "abstract": _openalex_abstract(w.get("abstract_inverted_index")),
                    "authors": authors, "venue": venue or ("preprint" if is_pre else "unknown venue"),
                    "venue_type": "preprint" if is_pre else ("journal" if venue else "other"), "type": wtype,
                    "published_date": w.get("publication_date") or "", "doi": doi, "arxiv_id": None,
                    "url": (w.get("doi") or loc.get("landing_page_url") or w.get("id") or ""),
                    "pdf_url": loc.get("pdf_url") or "", "peer_reviewed": (not is_pre) and bool(venue),
                    "is_preprint": is_pre, "published_doi": None, "sources": ["openalex"], "categories": [],
                    "openalex_id": w.get("id"),
                }
            if len(results) < 100:
                break
            time.sleep(0.5)
        time.sleep(1.0)  # pace queries; anonymous OpenAlex is quick to answer 429 when hit in bursts
    return list(out.values())


def fetch_europepmc(prof: dict, d_from: dt.date, d_to: dt.date, queries: list[str]) -> list[dict]:
    out: dict[str, dict] = {}
    for q in queries:
        cursor = "*"
        for _ in range(3):
            full_q = f"({q}) AND (FIRST_PDATE:[{d_from.isoformat()} TO {d_to.isoformat()}])"
            params = {"query": full_q, "format": "json", "pageSize": 100, "resultType": "core", "cursorMark": cursor}
            url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params)
            data = http_json(url)
            results = (data.get("resultList") or {}).get("result") or []
            for r in results:
                doi = norm_doi(r.get("doi"))
                key = doi or ("epmc:" + str(r.get("id")))
                if key in out:
                    continue
                is_pre = (r.get("source") == "PPR")
                pubtypes = ((r.get("pubTypeList") or {}).get("pubType") or [])
                out[key] = {
                    "title": " ".join((r.get("title") or "").split()).rstrip("."),
                    "abstract": strip_tags(r.get("abstractText") or ""),
                    "authors": [a.strip() for a in (r.get("authorString") or "").rstrip(".").split(",") if a.strip()],
                    "venue": r.get("journalTitle") or ("preprint" if is_pre else ""),
                    "venue_type": "preprint" if is_pre else "journal",
                    "type": "; ".join(pubtypes) if pubtypes else ("preprint" if is_pre else "journal-article"),
                    "published_date": r.get("firstPublicationDate") or str(r.get("pubYear") or ""),
                    "doi": doi, "arxiv_id": None,
                    "url": (f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/{r.get('source')}/{r.get('id')}"),
                    "pdf_url": "", "peer_reviewed": not is_pre, "is_preprint": is_pre, "published_doi": None,
                    "sources": ["europepmc"], "categories": [], "pmid": r.get("pmid"),
                }
            nxt = data.get("nextCursorMark")
            if not nxt or nxt == cursor or len(results) < 100:
                break
            cursor = nxt
            time.sleep(0.3)
    return list(out.values())


def fetch_crossref(prof: dict, d_from: dt.date, d_to: dt.date, queries: list[str]) -> list[dict]:
    out: dict[str, dict] = {}
    mailto = _mailto(prof)
    for q in queries:
        params = {
            "query.bibliographic": q, "rows": 50, "sort": "published", "order": "desc",
            "filter": f"from-pub-date:{d_from.isoformat()},until-pub-date:{d_to.isoformat()},type:journal-article",
        }
        if mailto:
            params["mailto"] = mailto
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        data = http_json(url)
        for it in (data.get("message") or {}).get("items") or []:
            doi = norm_doi(it.get("DOI"))
            if not doi or doi in out:
                continue
            date = None
            for k in ("published-online", "published-print", "published", "created"):
                if it.get(k) and it[k].get("date-parts"):
                    date = parse_date(it[k]["date-parts"])
                    if date:
                        break
            out[doi] = {
                "title": " ".join(((it.get("title") or [""])[0]).split()),
                "abstract": strip_tags(it.get("abstract") or ""),
                "authors": [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in it.get("author") or []],
                "venue": (it.get("container-title") or [""])[0], "venue_type": "journal", "type": it.get("type") or "journal-article",
                "published_date": date.isoformat() if date else "", "doi": doi, "arxiv_id": None,
                "url": it.get("URL") or f"https://doi.org/{doi}", "pdf_url": "",
                "peer_reviewed": True, "is_preprint": False, "published_doi": None, "sources": ["crossref"], "categories": [],
            }
        time.sleep(0.5)
    return list(out.values())


def fetch_semantic_scholar(prof: dict, d_from: dt.date, d_to: dt.date, queries: list[str]) -> list[dict]:
    out: dict[str, dict] = {}
    headers = {}
    key = os.environ.get("S2_API_KEY")
    if key:
        headers["x-api-key"] = key
    for q in queries:
        params = {
            "query": q, "limit": 100, "publicationDateOrYear": f"{d_from.isoformat()}:{d_to.isoformat()}",
            "fields": "title,abstract,authors,venue,journal,publicationDate,externalIds,url,publicationTypes,openAccessPdf",
        }
        url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
        data = http_json(url, headers=headers)
        for p in data.get("data") or []:
            ext = p.get("externalIds") or {}
            doi = norm_doi(ext.get("DOI"))
            aid = ext.get("ArXiv")
            k = doi or (("arxiv:" + aid) if aid else ("s2:" + str(p.get("paperId"))))
            if k in out:
                continue
            venue = p.get("venue") or ((p.get("journal") or {}).get("name")) or ""
            is_pre = bool(aid) and not venue or venue.lower() in ("arxiv.org", "biorxiv", "biorxiv.org")
            out[k] = {
                "title": p.get("title") or "", "abstract": p.get("abstract") or "",
                "authors": [a.get("name") for a in p.get("authors") or [] if a.get("name")],
                "venue": venue or ("preprint" if is_pre else "unknown venue"),
                "venue_type": "preprint" if is_pre else "journal", "type": "; ".join(p.get("publicationTypes") or []) or "unknown",
                "published_date": p.get("publicationDate") or "", "doi": doi, "arxiv_id": aid,
                "url": p.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                "pdf_url": ((p.get("openAccessPdf") or {}).get("url") or ""), "peer_reviewed": not is_pre,
                "is_preprint": is_pre, "published_doi": None, "sources": ["semantic_scholar"], "categories": [],
            }
        time.sleep(1.2)
    return list(out.values())


# ----------------------------------------------------------------------------
# Merge, deduplicate, prescreen
# ----------------------------------------------------------------------------

def normalise_record(r: dict) -> dict:
    """Fill defaults for records supplied by hand or through the WebFetch bridge (any field may be missing)."""
    r = dict(r)
    r["title"] = " ".join(str(r.get("title") or "").split())
    r["abstract"] = " ".join(str(r.get("abstract") or "").split())
    authors = r.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in re.split(r"[;,]|\band\b", authors) if a.strip()]
    r["authors"] = [str(a) for a in authors]
    r["doi"] = norm_doi(r.get("doi"))
    aid = r.get("arxiv_id")
    if aid:
        m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", str(aid))
        r["arxiv_id"] = m.group(1) if m else str(aid)
    venue = str(r.get("venue") or "").strip()
    src = r.get("source")
    sources = r.get("sources") or ([src] if src else ["bridge"])
    r["sources"] = [str(x) for x in sources]
    is_pre = r.get("is_preprint")
    if is_pre is None:
        is_pre = bool(r.get("arxiv_id")) or any(k in venue.lower() for k in ("arxiv", "biorxiv", "preprint", "ecoevorxiv"))
    r["is_preprint"] = bool(is_pre)
    if not venue:
        venue = "arXiv" if r.get("arxiv_id") else ("preprint" if is_pre else "unknown venue")
    r["venue"] = venue
    r["venue_type"] = r.get("venue_type") or ("preprint" if is_pre else "journal")
    r["type"] = r.get("type") or ("preprint" if is_pre else "journal-article")
    r["peer_reviewed"] = bool(r.get("peer_reviewed", not is_pre))
    d = parse_date(r.get("published_date") or r.get("date"))
    r["published_date"] = d.isoformat() if d else ""
    if not r.get("url"):
        r["url"] = f"https://doi.org/{r['doi']}" if r["doi"] else (f"https://arxiv.org/abs/{r['arxiv_id']}" if r.get("arxiv_id") else "")
    r.setdefault("pdf_url", "")
    r.setdefault("published_doi", None)
    r.setdefault("categories", [])
    return r


def merge_records(records: list[dict]) -> list[dict]:
    """Merge by DOI -> arXiv id -> normalised title; keep the longest abstract and the union of sources."""
    by_key: dict[str, dict] = {}
    title_index: dict[str, str] = {}
    for rec in records:
        rec = dict(rec)
        rec["doi"] = norm_doi(rec.get("doi"))
        nt = norm_title(rec.get("title", ""))
        if not nt:
            continue
        key = canonical_id(rec)
        if key not in by_key and nt in title_index:
            key = title_index[nt]
        if key in by_key:
            cur = by_key[key]
            if len(rec.get("abstract") or "") > len(cur.get("abstract") or ""):
                cur["abstract"] = rec["abstract"]
            for f in ("doi", "arxiv_id", "pdf_url", "published_doi", "pmid", "openalex_id"):
                if not cur.get(f) and rec.get(f):
                    cur[f] = rec[f]
            if (not cur.get("venue") or cur.get("venue_type") == "preprint") and rec.get("venue_type") == "journal":
                cur["venue"], cur["venue_type"], cur["peer_reviewed"], cur["is_preprint"] = rec["venue"], "journal", True, False
                cur["url"] = rec.get("url") or cur.get("url")
            if len(rec.get("authors") or []) > len(cur.get("authors") or []):
                cur["authors"] = rec["authors"]
            cur["sources"] = sorted(set(cur.get("sources", [])) | set(rec.get("sources", [])))
            if not cur.get("published_date") and rec.get("published_date"):
                cur["published_date"] = rec["published_date"]
        else:
            by_key[key] = rec
            title_index[nt] = key
    for key, rec in by_key.items():
        rec["id"] = canonical_id(rec)
        rec["norm_title"] = norm_title(rec.get("title", ""))
    return list(by_key.values())


_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _term_pattern(term: str) -> re.Pattern | None:
    """Phrase matcher: spaces/hyphens/dashes are interchangeable, a trailing plural (s/es) is allowed, non-alphanumeric boundaries required."""
    key = term.lower().strip()
    if not key:
        return None
    pat = _PATTERN_CACHE.get(key)
    if pat is None:
        parts = [re.escape(x) for x in re.split(r"[\s\-\u2013\u2014]+", key) if x]
        if not parts:
            return None
        body = r"[\s\-\u2013\u2014]+".join(parts)
        pat = re.compile(r"(?<![a-z0-9])" + body + r"(?:e?s)?(?![a-z0-9])")
        _PATTERN_CACHE[key] = pat
    return pat


def _term_hits(text: str, terms: list[str]) -> list[str]:
    """Return matched terms; spellings that differ only by space/hyphen count once."""
    hits, seen_keys = [], set()
    for t in terms:
        pat = _term_pattern(t)
        if pat is None:
            continue
        key = re.sub(r"[\s\-\u2013\u2014]+", " ", t.lower().strip())
        if key in seen_keys:
            continue
        if pat.search(text):
            hits.append(t)
            seen_keys.add(key)
    return hits


def _author_hits(authors: list[str], watchlist: list[dict | str]) -> list[str]:
    """Author watchlist matching.

    Auto-generated variants only permute the full name ("peter chesson" / "chesson peter").
    "Surname + initial" forms (e.g. "Wang S") are NOT generated automatically because they
    produce many false positives; list them explicitly under `variants` in the profile if you
    need to match Europe PMC's "Chesson P" style.
    """

    def norm(a: str) -> str:
        a = a.lower().replace("-", " ").replace("’", "'")
        a = re.sub(r"[^a-z' ]", " ", a).replace("'", " ")
        return " ".join(a.split())

    def perms(n: str) -> set[str]:
        toks = n.split()
        out = {n}
        if len(toks) >= 2:
            out.add(" ".join([toks[-1]] + toks[:-1]))  # last first middle
            out.add(" ".join(toks[1:] + [toks[0]]))    # middle last first (rare but cheap)
            out.add(f"{toks[0]} {toks[-1]}")           # drop middle names
            out.add(f"{toks[-1]} {toks[0]}")
        return out

    author_forms: list[set[str]] = [perms(norm(a)) for a in authors if a]
    hits = []
    for w in watchlist:
        name = w if isinstance(w, str) else w.get("name", "")
        forms = perms(norm(name))
        if isinstance(w, dict):
            for alt in w.get("variants", []):
                forms |= perms(norm(alt))
        forms.discard("")
        if any(af & forms for af in author_forms):
            hits.append(name)
    return hits


def journal_tier(venue: str, tiers: dict) -> int | None:
    v = norm_title(venue)
    if not v:
        return None
    for t in (1, 2, 3):
        for j in tiers.get(f"tier_{t}", []) or []:
            if norm_title(j) == v:
                return t
    return None


def prescreen(rec: dict, prof: dict, focus: str | None = None) -> dict:
    """Deterministic prescreen. Returns a 0-100 score (after a saturating transform) plus an explainable breakdown.

    raw = sum_group weight x (title hit 1.0 / abstract-only 0.5) x (1 + multi-term bonus) [+ weak_terms x weak_multiplier]
          + cross-topic bonuses + journal tier + watched author - missing abstract
    score = 100 x (1 - exp(-raw / saturation))   # keeps resolution at the top instead of hard-capping
    """
    import math

    ps = prof.get("prescreen", {})
    title_mult = float(ps.get("title_multiplier", 1.0))
    abs_mult = float(ps.get("abstract_multiplier", 0.5))
    weak_mult = float(ps.get("weak_multiplier", 0.35))
    saturation = float(ps.get("saturation", 80))
    tier_bonus = {int(k): v for k, v in (ps.get("tier_bonus") or {"1": 10, "2": 6, "3": 3}).items()}
    author_bonus = float(ps.get("author_bonus", 15))
    title = (rec.get("title") or "").lower()
    abstract = (rec.get("abstract") or "").lower()
    text_all = title + " \n " + abstract

    result: dict[str, Any] = {"score": 0.0, "raw": 0.0, "hits": {}, "bonuses": [], "excluded": None, "journal_tier": None, "author_hits": []}

    groups = prof.get("topic_groups") or []
    focus_cfg = (prof.get("focus_modes") or {}).get(focus) if focus else None
    allowed_labels = set(focus_cfg.get("groups", [])) if focus_cfg and focus_cfg.get("groups") else None

    raw = 0.0
    for g in groups:
        label = g["label"]
        weight = float(g["weight"])
        if allowed_labels is not None and label not in allowed_labels:
            weight *= 0.4  # in focus mode, non-focus groups are down-weighted rather than removed
        t_hits = _term_hits(title, g.get("terms", []))
        a_hits = _term_hits(abstract, g.get("terms", []))
        wt_hits = _term_hits(title, g.get("weak_terms", []))
        wa_hits = _term_hits(abstract, g.get("weak_terms", []))
        strong = sorted(set(t_hits) | set(a_hits))
        weak = sorted(set(wt_hits) | set(wa_hits))
        if not strong and not weak:
            continue
        result["hits"][label] = strong + [f"~{w}" for w in weak]  # "~" marks a weak term
        if strong:
            base = weight * (title_mult if t_hits else abs_mult)
            extra = min(0.30, 0.10 * (len(strong) - 1))
            raw += base * (1 + extra)
        if weak:
            raw += weight * weak_mult * (title_mult if wt_hits else abs_mult)

    excl = _term_hits(text_all, prof.get("exclusion_terms") or [])
    if excl:
        core_title_hit = any(_term_hits(title, g.get("terms", [])) for g in groups if float(g["weight"]) >= 90)
        if core_title_hit:
            raw -= 40
            result["bonuses"].append(f"exclusion term hit but core group in title; -40 instead of excluding: {excl}")
        else:
            result["excluded"] = "exclusion term: " + ", ".join(excl)
            return result

    if not result["hits"]:
        result["excluded"] = "no topic-group hit"
        return result
    if raw <= 0:
        result["excluded"] = "weak-only hit too low"
        return result

    for cb in prof.get("cross_topic_bonuses") or []:
        labels = cb.get("labels") or []
        if labels and all(any(not h.startswith("~") for h in result["hits"].get(l, [])) for l in labels):
            raw += float(cb.get("bonus", 10))
            result["bonuses"].append(f"cross-topic +{cb.get('bonus', 10)}: {' + '.join(labels)}" + (f" ({cb['reason']})" if cb.get("reason") else ""))

    tier = journal_tier(rec.get("venue", ""), prof.get("journal_tiers") or {})
    result["journal_tier"] = tier
    if tier:
        raw += float(tier_bonus.get(tier, 0))
        result["bonuses"].append(f"journal tier T{tier} +{tier_bonus.get(tier, 0)}")

    ah = _author_hits(rec.get("authors") or [], prof.get("author_watchlist") or [])
    result["author_hits"] = ah
    if ah:
        raw += author_bonus
        result["bonuses"].append(f"watched author +{author_bonus:g}: {', '.join(ah)}")

    if not rec.get("abstract"):
        raw -= 5
        result["bonuses"].append("no abstract -5 (needs verification)")

    raw = max(0.0, raw)
    result["raw"] = round(raw, 1)
    result["score"] = round(100.0 * (1.0 - math.exp(-raw / saturation)), 1)
    return result


# ----------------------------------------------------------------------------
# State: dedup history and research memory
# ----------------------------------------------------------------------------

def seen_path(workdir: Path) -> Path:
    return workdir / "data" / "seen_papers.json"


def memory_path(workdir: Path) -> Path:
    return workdir / "data" / "research_memory.json"


def load_seen(workdir: Path) -> dict:
    return load_json(seen_path(workdir), {"version": 1, "papers": {}})


def load_memory(workdir: Path) -> dict:
    return load_json(memory_path(workdir), {"version": 1, "entries": [], "tag_counts": {}, "project_counts": {}})


# ----------------------------------------------------------------------------
# collect
# ----------------------------------------------------------------------------

def compute_window(prof: dict, mode: str, days: int | None, since: str | None, until: str | None) -> tuple[dt.date, dt.date]:
    w = prof.get("window", {})
    end = parse_date(until) or today()
    if since:
        start = parse_date(since)
        if not start:
            raise SystemExit(f"cannot parse --since: {since}")
        return start, end
    if days is None:
        days = {"daily": int(w.get("default_days", 2)), "weekly": int(w.get("weekly_days", 7)), "catchup": int(w.get("catchup_days", 30))}.get(mode, 2)
    start = end - dt.timedelta(days=max(0, days - 1))
    return start, end


def source_queries(prof: dict, source: str, focus: str | None, extra_topic: str | None) -> list[str]:
    qs = list((prof.get("queries") or {}).get(source) or [])
    if focus:
        fm = (prof.get("focus_modes") or {}).get(focus) or {}
        fq = (fm.get("queries") or {}).get(source)
        if fq:
            qs = list(fq)
    if extra_topic:
        qs.append(extra_topic)
    return qs


def run_sources(prof: dict, d_from: dt.date, d_to: dt.date, focus: str | None, extra_topic: str | None, offline: Path | None) -> tuple[list[dict], dict]:
    stats: dict[str, dict] = {}
    records: list[dict] = []
    if offline:
        fx = load_json(offline, {})
        status = "bridge" if fx.get("bridge") else "fixture"
        recs = [normalise_record(r) for r in fx.get("records", []) if r.get("title")]
        for r in recs:
            for src in r.get("sources") or [status]:
                stats.setdefault(src, {"count": 0, "status": status})
                stats[src]["count"] += 1
        for src, note in (fx.get("failed") or {}).items():
            stats[src] = {"count": 0, "status": f"failed: {note}"}
        return recs, stats
    enabled = prof.get("sources") or {}
    runners = {
        "arxiv": lambda: fetch_arxiv(prof, d_from, d_to),
        "biorxiv": lambda: fetch_biorxiv(prof, d_from, d_to),
        "openalex": lambda: fetch_openalex(prof, d_from, d_to, source_queries(prof, "openalex", focus, extra_topic)),
        "europepmc": lambda: fetch_europepmc(prof, d_from, d_to, source_queries(prof, "europepmc", focus, extra_topic)),
        "crossref": lambda: fetch_crossref(prof, d_from, d_to, source_queries(prof, "crossref", focus, extra_topic)),
        "semantic_scholar": lambda: fetch_semantic_scholar(prof, d_from, d_to, source_queries(prof, "semantic_scholar", focus, extra_topic)),
    }
    for name, fn in runners.items():
        if not enabled.get(name, False):
            stats[name] = {"count": 0, "status": "disabled"}
            continue
        t0 = time.time()
        try:
            recs = fn()
            records.extend(recs)
            stats[name] = {"count": len(recs), "status": "ok", "seconds": round(time.time() - t0, 1)}
            log(f"  [{name}] {len(recs)} records ({stats[name]['seconds']}s)")
        except Exception as exc:  # one failing source must not stop the others
            stats[name] = {"count": 0, "status": f"failed: {type(exc).__name__}: {truncate(str(exc), 160)}"}
            log(f"  [{name}] {stats[name]['status']}")
    return records, stats


def cmd_collect(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    prof_path = resolve_profile_path(workdir, args.profile)
    prof = load_profile(prof_path)
    ps = prof.get("prescreen", {})
    w = prof.get("window", {})
    high = float(ps.get("high_score", 70))
    queue_min = float(args.min_score if args.min_score is not None else ps.get("queue_min_score", 30))
    max_queue = int(args.max_queue or ps.get("max_queue", 60))

    d_from, d_to = compute_window(prof, args.mode, args.days, args.since, args.until)
    offline = Path(args.offline).expanduser() if args.offline else (Path(args.records).expanduser() if getattr(args, "records", None) else None)
    fetch_mode = "fixture" if args.offline else ("bridge" if getattr(args, "records", None) else "api")
    log(f"lit-radar collect · mode {args.mode}" + (f" · focus={args.focus}" if args.focus else "") + f" · window {d_from} -> {d_to} · profile {prof_path}")
    if args.focus and args.focus not in (prof.get("focus_modes") or {}):
        raise SystemExit(f"unknown focus mode {args.focus!r}; available: {', '.join((prof.get('focus_modes') or {}).keys())}")

    records, stats = run_sources(prof, d_from, d_to, args.focus, args.topic, offline)
    expanded = False
    merged = merge_records(records)
    for rec in merged:
        rec["prescreen"] = prescreen(rec, prof, args.focus)
    n_high = sum(1 for r in merged if r["prescreen"]["score"] >= high and not r["prescreen"]["excluded"])
    min_high = int(w.get("min_high_score_candidates", 3))
    expand_days = int(w.get("expand_to_days", 7))
    all_failed = all(str(v.get("status", "")).startswith("failed") or v.get("status") == "disabled" for v in stats.values())
    if (not offline and not all_failed and args.mode == "daily" and not args.since and args.days is None
            and n_high < min_high and (d_to - d_from).days + 1 < expand_days):
        log(f"  only {n_high} high-scoring candidates (< {min_high}); expanding the window to the last {expand_days} days...")
        d_from2 = d_to - dt.timedelta(days=expand_days - 1)
        records2, stats2 = run_sources(prof, d_from2, d_to, args.focus, args.topic, None)
        for k, v in stats2.items():
            stats[k] = {"count": stats.get(k, {}).get("count", 0) + v.get("count", 0), "status": v.get("status")}
            if v.get("status") != "disabled":
                stats[k]["expanded_window"] = True
        merged = merge_records(records + records2)
        for rec in merged:
            rec["prescreen"] = prescreen(rec, prof, args.focus)
        d_from, expanded = d_from2, True

    if all_failed and not offline:  # bridge/fixture runs never trip this
        log("All sources failed or are disabled. Stopping; check network access or use the web-search fallback in SKILL.md.")
        run_dir = workdir / "runs" / today().isoformat()
        atomic_write_json(run_dir / "collect_failed.json", {"date": today().isoformat(), "sources": stats})
        return 2

    # dedup history
    seen = load_seen(workdir) if not args.include_seen else {"papers": {}}
    seen_titles = {v.get("norm_title"): k for k, v in seen.get("papers", {}).items() if v.get("norm_title")}
    queue, dropped_seen, updates, excluded_reasons = [], 0, 0, {}
    for rec in merged:
        p = rec["prescreen"]
        if p["excluded"]:
            reason = p["excluded"].split(":")[0]
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1
            continue
        if p["score"] < queue_min:
            excluded_reasons["below queue threshold"] = excluded_reasons.get("below queue threshold", 0) + 1
            continue
        if rec["id"] in seen.get("papers", {}):
            dropped_seen += 1
            continue
        prev_key = seen_titles.get(rec["norm_title"])
        if prev_key and prev_key != rec["id"]:
            if rec.get("venue_type") == "journal" and seen["papers"][prev_key].get("is_preprint"):
                rec["update_of"] = prev_key  # preprint already delivered, now published: mark as an update
                updates += 1
            else:
                dropped_seen += 1
                continue
        queue.append(rec)
    queue.sort(key=lambda r: (-r["prescreen"]["score"], r.get("published_date") or ""))
    queue = queue[:max_queue]

    run_date = today().isoformat()
    run_dir = workdir / "runs" / (run_date + (f"-{args.tag}" if args.tag else ""))
    meta = {
        "date": run_date, "mode": args.mode, "focus": args.focus, "extra_topic": args.topic,
        "window": {"from": d_from.isoformat(), "to": d_to.isoformat(), "expanded": expanded},
        "profile": str(prof_path), "profile_name": prof.get("profile_name"), "fixture": fetch_mode == "fixture", "fetch_mode": fetch_mode,
        "sources": stats,
        "counts": {"fetched": len(records), "merged": len(merged), "queue": len(queue), "high_score": n_high,
                   "dropped_seen": dropped_seen, "preprint_to_published": updates},
        "excluded_reasons": excluded_reasons, "thresholds": {"queue_min_score": queue_min, "high_score": high},
        "version": VERSION,
    }
    atomic_write_json(run_dir / "review_queue.json", {"meta": meta, "candidates": queue})
    atomic_write_text(run_dir / "review_queue.md", render_queue_md(meta, queue, prof))
    print(json.dumps({"run_dir": str(run_dir), "review_queue_md": str(run_dir / "review_queue.md"),
                      "review_queue_json": str(run_dir / "review_queue.json"), "counts": meta["counts"],
                      "window": meta["window"], "sources": {k: v.get("status") for k, v in stats.items()}},
                     ensure_ascii=False, indent=2))
    return 0


def render_queue_md(meta: dict, queue: list[dict], prof: dict) -> str:
    c, w = meta["counts"], meta["window"]
    src = " / ".join(f"{k} {v.get('count', 0)}" + ("" if v.get("status") in ("ok", "fixture") else f" ({v.get('status')})") for k, v in meta["sources"].items() if v.get("status") != "disabled")
    lines = [
        f"# Lit Radar review queue · {meta['date']}" + (f" · focus={meta['focus']}" if meta.get("focus") else ""),
        "",
        f"Window {w['from']} -> {w['to']}" + (" (auto-expanded)" if w.get("expanded") else "") + f" · sources: {src}",
        f"Fetched {c['fetched']} -> deduplicated {c['merged']} -> queued {c['queue']} (prescreen >= {meta['thresholds']['queue_min_score']:g}) · high-scoring (>= {meta['thresholds']['high_score']:g}) {c['high_score']} · dropped as already delivered {c['dropped_seen']} · preprint-to-published updates {c['preprint_to_published']}",
    ]
    if meta.get("fixture"):
        lines.append("")
        lines.append("> WARNING: this queue was built from bundled fictional records (selftest / --offline), not real literature.")
    elif meta.get("fetch_mode") == "bridge":
        lines.append("")
        lines.append("> Records were fetched through the WebFetch bridge (sandbox egress blocked). Abstracts may be missing; verify candidates via their DOI/arXiv page before scoring.")
    if meta.get("excluded_reasons"):
        lines.append("Excluded: " + "; ".join(f"{k} {v}" for k, v in meta["excluded_reasons"].items()))
    lines += ["", "> Prescreen scores are for ordering only. Read the abstract, verify the evidence, then re-score independently; never recommend on title or keywords alone.", "", "## Candidates (sorted by prescreen score)", ""]
    if not queue:
        lines.append("(No candidates entered the queue in this window. Consider weekly mode or check the profile.)")
    for i, r in enumerate(queue, 1):
        p = r["prescreen"]
        authors = r.get("authors") or []
        auth = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
        flags = []
        if r.get("is_preprint"):
            flags.append("preprint, not peer reviewed")
        if r.get("update_of"):
            flags.append("UPDATE: delivered earlier as a preprint, now published")
        if not r.get("abstract"):
            flags.append("no abstract - verify")
        hits = "; ".join(f"{k}[{', '.join(v)}]" for k, v in p["hits"].items())
        lines.append(f"### [{i}] {p['score']:g} | {r.get('title', '')}")
        lines.append(f"- id: `{r['id']}` · {r.get('venue', '')} · {r.get('published_date', '')} · {r.get('type', '')}" + (f" · {' · '.join(flags)}" if flags else ""))
        lines.append(f"- Authors: {auth or '(unknown)'} · Link: {r.get('url', '')}" + (f" · DOI: {r['doi']}" if r.get("doi") else ""))
        lines.append(f"- Hits: {hits}" + (f" · T{p['journal_tier']}" if p.get("journal_tier") else "") + (f" · watched authors: {', '.join(p['author_hits'])}" if p.get("author_hits") else ""))
        if p.get("bonuses"):
            lines.append(f"- Adjustments: {'; '.join(p['bonuses'])}")
        lines.append(f"- Abstract: {truncate(r.get('abstract') or '(no abstract - open the DOI/link and verify before scoring)', int(prof.get('prescreen', {}).get('abstract_chars', 1200)))}")
        lines.append("")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# queries: the search plan (also used by the web-search fallback)
# ----------------------------------------------------------------------------

def cmd_queries(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    prof = load_profile(resolve_profile_path(workdir, args.profile))
    d_from, d_to = compute_window(prof, args.mode, args.days, args.since, args.until)
    print(f"# Search plan · window {d_from} -> {d_to}" + (f" · focus={args.focus}" if args.focus else ""))
    print("\n## Sources and queries")
    for src in ("openalex", "europepmc", "crossref", "semantic_scholar"):
        enabled = (prof.get("sources") or {}).get(src)
        qs = source_queries(prof, src, args.focus, args.topic)
        print(f"\n### {src} ({'enabled' if enabled else 'disabled'})")
        for q in qs:
            print(f"- {q}")
    print(f"\n### arxiv ({'enabled' if (prof.get('sources') or {}).get('arxiv') else 'disabled'}) · categories: {', '.join(prof.get('arxiv', {}).get('categories', []))} · fetched by submittedDate, scored locally")
    print(f"### biorxiv ({'enabled' if (prof.get('sources') or {}).get('biorxiv') else 'disabled'}) · categories: {', '.join(prof.get('biorxiv', {}).get('categories', []))}")
    print("\n## Web-search fallback (when the sandbox cannot reach the APIs)")
    print("Run each search below, keep results from the last 7 days only, then write reviewed.json directly (see SKILL.md) and render it.")
    core_terms: list[str] = []
    for g in sorted(prof.get("topic_groups") or [], key=lambda g: -g["weight"])[:4]:
        core_terms += g["terms"][:4]
    year = d_to.year
    for t in core_terms[:12]:
        print(f'- "{t}" {year} (arXiv OR bioRxiv OR "Ecology Letters" OR "American Naturalist" OR Ecology)')
    print(f"- site:arxiv.org q-bio.PE coexistence {year}")
    print(f'- site:biorxiv.org ecology coexistence OR "storage effect" {year}')
    print(f'- site:onlinelibrary.wiley.com "Ecology Letters" early view coexistence {year}')
    return 0


def bridge_urls(prof: dict, d_from: dt.date, d_to: dt.date, focus: str | None, extra_topic: str | None, per_page: int) -> list[dict]:
    """Small-page API URLs that a WebFetch-style tool can retrieve one by one."""
    urls: list[dict] = []
    enabled = prof.get("sources") or {}
    span = f"[{d_from.strftime('%Y%m%d')}0000 TO {d_to.strftime('%Y%m%d')}2359]"
    if enabled.get("arxiv", False):
        for cat in (prof.get("arxiv", {}).get("categories") or ["q-bio.PE"]):
            q = urllib.parse.urlencode({"search_query": f"cat:{cat} AND submittedDate:{span}", "sortBy": "submittedDate", "sortOrder": "descending", "max_results": per_page * 2})
            urls.append({"source": "arxiv", "label": f"arXiv {cat}", "url": "https://export.arxiv.org/api/query?" + q, "format": "atom"})
    if enabled.get("biorxiv", False):
        server = prof.get("biorxiv", {}).get("server", "biorxiv")
        cats = ", ".join(prof.get("biorxiv", {}).get("categories") or ["ecology"])
        for cursor in (0, 100, 200):
            urls.append({"source": "biorxiv", "label": f"bioRxiv cursor {cursor} (keep only categories: {cats}; stop when the page is empty)",
                         "url": f"https://api.biorxiv.org/details/{server}/{d_from.isoformat()}/{d_to.isoformat()}/{cursor}", "format": "json"})
    if enabled.get("openalex", False):
        for i, q in enumerate(source_queries(prof, "openalex", focus, extra_topic), 1):
            flt = f"from_publication_date:{d_from.isoformat()},to_publication_date:{d_to.isoformat()},title_and_abstract.search:{q}"
            params = {"filter": flt, "per-page": per_page, "sort": "publication_date:desc", "select": "doi,title,publication_date,type,primary_location,authorships"}
            if _mailto(prof):
                params["mailto"] = _mailto(prof)
            urls.append({"source": "openalex", "label": f"OpenAlex query {i}", "url": "https://api.openalex.org/works?" + urllib.parse.urlencode(params), "format": "json"})
    if enabled.get("europepmc", False):
        for i, q in enumerate(source_queries(prof, "europepmc", focus, extra_topic), 1):
            params = {"query": f"({q}) AND (FIRST_PDATE:[{d_from.isoformat()} TO {d_to.isoformat()}])", "format": "json", "pageSize": max(10, per_page // 2), "resultType": "core"}
            urls.append({"source": "europepmc", "label": f"Europe PMC query {i}", "url": "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(params), "format": "json"})
    return urls


BRIDGE_PROMPT = (
    "Return EVERY record in this response as a JSON array, nothing else. One object per record with exactly these keys: "
    "title, abstract (empty string if absent), authors (array of full names), venue (journal or 'arXiv'/'bioRxiv'), "
    "published_date (YYYY-MM-DD), doi (or null), arxiv_id (or null), url, is_preprint (true/false), source ('<SOURCE>'). "
    "Copy titles and DOIs verbatim; do not summarise, skip, invent or reorder records."
)


def cmd_plan(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    prof = load_profile(resolve_profile_path(workdir, args.profile))
    d_from, d_to = compute_window(prof, args.mode, args.days, args.since, args.until)
    urls = bridge_urls(prof, d_from, d_to, args.focus, args.topic, int(args.per_page))
    run_dir = workdir / "runs" / today().isoformat()
    records_path = run_dir / "bridge_records.json"
    plan = {"date": today().isoformat(), "window": {"from": d_from.isoformat(), "to": d_to.isoformat()}, "mode": args.mode, "focus": args.focus,
            "records_file": str(records_path), "prompt_template": BRIDGE_PROMPT, "urls": urls}
    atomic_write_json(run_dir / "fetch_plan.json", plan)
    lines = [f"# WebFetch bridge plan · {plan['date']} · window {d_from} -> {d_to}", "",
             "The sandbox cannot call the APIs directly, but the WebFetch tool can. For each URL below:", "",
             "1. WebFetch the URL with this prompt (replace <SOURCE> by the source name):", "", f"   {BRIDGE_PROMPT}", "",
             "2. Append the returned objects to the `records` array of the file below (create it on the first URL):", "", f"   {records_path}", "",
             '   File shape: {"bridge": true, "records": [ ... ], "failed": {"source": "reason"}}  - list sources whose fetch failed under "failed".', "",
             f"3. Then run: python3 scripts/lit_radar.py collect --mode {args.mode}" + (f" --focus {args.focus}" if args.focus else "") + f" --records {records_path} --workdir {workdir}", "",
             "Notes: bioRxiv pages hold 100 records each - keep only the listed categories and stop at the first empty page. OpenAlex responses carry no abstract; the review step verifies candidates via their DOI page. If WebFetch truncates a page, re-fetch with a smaller window (--since/--until) or fewer queries (--focus).", "",
             "## URLs", ""]
    for i, u in enumerate(urls, 1):
        lines.append(f"{i}. [{u['source']}] {u['label']}")
        lines.append(f"   {u['url']}")
        lines.append("")
    atomic_write_text(run_dir / "fetch_plan.md", "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(json.dumps({"fetch_plan": str(run_dir / "fetch_plan.md"), "records_file": str(records_path), "n_urls": len(urls)}, ensure_ascii=False))
    return 0


# ----------------------------------------------------------------------------
# memory
# ----------------------------------------------------------------------------

def memory_context(mem: dict, last: int = 10, max_chars: int = 3000) -> str:
    entries = mem.get("entries", [])[-last:]
    if not entries:
        return "(Research memory is empty: first run, or no report has been delivered yet.)"
    lines = ["# Research memory (recent deliveries)", ""]
    for e in reversed(entries):
        lines.append(f"## {e.get('date')} · {e.get('mode', 'daily')} · {e.get('n_recommended', 0)} recommended")
        for t in e.get("top", [])[:5]:
            lines.append(f"- {t.get('score', '')} {truncate(t.get('title', ''), 110)}" + (f" [{', '.join(t.get('tags', [])[:4])}]" if t.get("tags") else "") + (f" -> {', '.join(t.get('projects', []))}" if t.get("projects") else ""))
        if e.get("themes"):
            lines.append(f"- Themes: {'; '.join(e['themes'][:5])}")
        if e.get("research_ideas"):
            lines.append(f"- Ideas already proposed: {'; '.join(truncate(x, 90) for x in e['research_ideas'][:3])}")
        if e.get("open_verification"):
            lines.append(f"- Still to verify: {'; '.join(truncate(x, 80) for x in e['open_verification'][:3])}")
        lines.append("")
    tc = sorted((mem.get("tag_counts") or {}).items(), key=lambda kv: -kv[1])[:12]
    if tc:
        lines.append("Tag totals: " + ", ".join(f"{k}x{v}" for k, v in tc))
    pc = sorted((mem.get("project_counts") or {}).items(), key=lambda kv: -kv[1])
    if pc:
        lines.append("Project-link totals: " + ", ".join(f"{k}x{v}" for k, v in pc))
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars] + "\n...(truncated)"


def cmd_memory(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    print(memory_context(load_memory(workdir), last=args.last))
    return 0


# ----------------------------------------------------------------------------
# render：reviewed.json → Markdown
# ----------------------------------------------------------------------------

def compute_score(article: dict, weights: dict) -> float:
    cs = article.get("component_scores") or {}
    total = 0.0
    for k, wgt in weights.items():
        total += float(cs.get(k, 0)) * float(wgt)
    return round(total, 1)


def tier_for(score: float, tiers: dict) -> str:
    if score >= float(tiers.get("★★★", 85)):
        return "★★★"
    if score >= float(tiers.get("★★", 70)):
        return "★★"
    return "★"


def validate_reviewed(rv: dict, prof: dict) -> list[str]:
    problems = []
    if not rv.get("date"):
        problems.append("date is missing")
    arts = rv.get("articles")
    if arts is None:
        problems.append("articles is missing (an empty list is allowed)")
        arts = []
    review = prof.get("review") or {}
    weights = review.get("weights") or REVIEW_WEIGHTS
    threshold = float(review.get("recommendation_threshold", 70))
    three_star = float((review.get("tiers") or {}).get("★★★", 85))
    min_eco = int(review.get("ecologist_summary_min_chars", 200))
    for i, a in enumerate(arts):
        tag = f"articles[{i}] {truncate(a.get('title', ''), 50)!r}"
        for f in ("title", "venue", "url", "why_worth_reading", "core_findings", "ecologist_summary"):
            if not a.get(f):
                problems.append(f"{tag}: {f} is missing")
        cs = a.get("component_scores") or {}
        missing = [k for k in weights if k not in cs]
        if missing:
            problems.append(f"{tag}: component_scores lacks {missing}")
        else:
            a["recommendation_score"] = compute_score(a, weights)
            if a["recommendation_score"] < threshold:
                problems.append(f"{tag}: recommendation score {a['recommendation_score']} is below the threshold {threshold:g}; move it to peripheral or drop it - never lower the bar to fill the list")
        if a.get("score_status") not in ("evidence_reviewed", "title_only"):
            problems.append(f"{tag}: score_status must be evidence_reviewed or title_only")
        if a.get("score_status") == "title_only" and a.get("recommendation_score", 0) >= three_star:
            problems.append(f"{tag}: a title_only paper cannot receive three stars")
        if len(a.get("why_worth_reading", "")) > 400:
            problems.append(f"{tag}: why_worth_reading exceeds 400 characters; aim for <= 60 words")
        eco = a.get("ecologist_summary") or ""
        if eco and len(eco) < min_eco:
            problems.append(f"{tag}: ecologist_summary is too short ({len(eco)} chars); write 80-160 words a general ecologist can follow")
        cf = a.get("core_findings") or []
        if isinstance(cf, list) and not (1 <= len(cf) <= 6):
            problems.append(f"{tag}: core_findings needs 1-6 items (3-5 recommended)")
        if a.get("is_preprint") and not a.get("peer_reviewed_note"):
            a["peer_reviewed_note"] = "preprint, not peer reviewed"
    maxn = int(review.get("max_recommendations", 10))
    if len(arts) > maxn:
        problems.append(f"{len(arts)} recommendations exceed the maximum of {maxn}")
    return problems


def _fmt_list(items: list[str] | None, indent: str = "  ") -> list[str]:
    return [f"{indent}- {x}" for x in (items or []) if x]


def render_report(rv: dict, prof: dict, meta: dict | None) -> str:
    review = prof.get("review") or {}
    weights = review.get("weights") or REVIEW_WEIGHTS
    tiers = review.get("tiers") or {"★★★": 85, "★★": 70}
    projects = {p["key"]: p.get("label", p["key"]) for p in prof.get("active_projects") or []}
    plain_label = review.get("plain_summary_label") or "In plain language"
    date = rv.get("date") or today().isoformat()
    try:
        weekday = dt.date.fromisoformat(date).strftime("%A")
    except Exception:
        weekday = ""
    mode = rv.get("mode") or (meta or {}).get("mode") or "daily"
    mode_label = {"daily": "Daily", "weekly": "Weekly", "catchup": "Catch-up", "focus": "Focus"}.get(mode, mode)
    win = rv.get("window") or (meta or {}).get("window") or {}
    arts = list(rv.get("articles") or [])
    for a in arts:
        a["recommendation_score"] = a.get("recommendation_score") or compute_score(a, weights)
        a["tier"] = a.get("tier") or tier_for(a["recommendation_score"], tiers)
    arts.sort(key=lambda a: -a["recommendation_score"])
    peripheral = rv.get("peripheral") or []
    counts = (meta or {}).get("counts") or {}
    srcs = (meta or {}).get("sources") or {}

    L: list[str] = []
    L.append(f"# Literature Radar · {date}" + (f" ({weekday})" if weekday else "") + f" · {mode_label}" + (f" · focus={rv.get('focus')}" if rv.get("focus") else ""))
    L.append("")
    head = []
    if win:
        head.append(f"Window {win.get('from', '?')} -> {win.get('to', '?')}" + (" (auto-expanded)" if win.get("expanded") else ""))
    ok_src = [k for k, v in srcs.items() if v.get("status") in ("ok", "fixture")]
    bad_src = [k for k, v in srcs.items() if str(v.get("status", "")).startswith("failed")]
    if ok_src:
        head.append("Sources: " + " / ".join(ok_src))
    if counts:
        head.append(f"Fetched {counts.get('fetched', '?')} -> deduplicated {counts.get('merged', '?')} -> queued {counts.get('queue', '?')} -> recommended {len(arts)}")
    else:
        head.append(f"Recommended {len(arts)}")
    L.append("> " + " · ".join(head))
    if (meta or {}).get("fixture") or rv.get("fixture"):
        L.append("> WARNING - example report: every paper below is fictional and only illustrates the format.")
    if bad_src:
        L.append(f"> WARNING - failed sources: {', '.join(bad_src)} (today's coverage is incomplete)")
    if (meta or {}).get("fetch_mode") == "bridge":
        L.append("> Records were retrieved through the WebFetch bridge because the sandbox blocked direct API access; coverage may be smaller than a direct run.")
    L.append("")

    s = rv.get("summary") or {}
    L.append("## At a glance")
    L.append("")
    if s.get("headline"):
        L.append(f"**{s['headline']}**")
        L.append("")
    if s.get("signal"):
        L.append(s["signal"])
        L.append("")
    top3 = s.get("top3") or []
    if top3:
        L.append("Top three to read first:")
        for i, t in enumerate(top3, 1):
            L.append(f"{i}. **{t.get('title', '')}** - {t.get('reason', '')}")
        L.append("")
    if not arts:
        L.append("No paper passed evidence review and reached the recommendation threshold today (the bar is not lowered to fill the list). See the peripheral scan below.")
        L.append("")

    def render_article(a: dict, idx: int) -> None:
        cs = a.get("component_scores") or {}
        L.append(f"### {idx}. [{a.get('title', '')}]({a.get('url', '')})")
        L.append("")
        L.append("- " + " · ".join(x for x in [
            a.get("authors_short", ""), a.get("venue", ""), a.get("publication_date", ""), a.get("article_type", ""),
            (a.get("peer_reviewed_note") or ("preprint, not peer reviewed" if a.get("is_preprint") else "")),
        ] if x))
        ids = []
        if a.get("doi"):
            ids.append(f"DOI [{a['doi']}](https://doi.org/{a['doi']})")
        if a.get("arxiv_id"):
            ids.append(f"arXiv:{a['arxiv_id']}")
        if ids:
            L.append("- " + " · ".join(ids))
        status = {"evidence_reviewed": "abstract/full text verified", "title_only": "title only (needs verification)"}.get(a.get("score_status"), a.get("score_status", ""))
        L.append(f"- **Score {a['recommendation_score']:g}** {a['tier']} · relevance {cs.get('relevance', '?')} / novelty {cs.get('novelty', '?')} / quality {cs.get('quality', '?')} / methodology {cs.get('methodology', '?')} / inspiration {cs.get('inspiration', '?')} · evidence: {status}"
                 + (" · STRONG RECOMMENDATION" if a.get("strong_recommendation") else ""))
        if a.get("strong_recommendation") and a.get("strong_recommendation_reasons"):
            L.append(f"- Why strongly recommended: {'; '.join(a['strong_recommendation_reasons'])}")
        L.append(f"- **Why you should read it**: {a.get('why_worth_reading', '')}")
        if a.get("ecologist_summary"):
            L.append(f"- **{plain_label}**: {a['ecologist_summary']}")
        if a.get("core_findings"):
            L.append("- **Core findings**:")
            L.extend(_fmt_list(a["core_findings"]))
        if a.get("project_links"):
            L.append("- **Links to your work**:")
            for pl in a["project_links"]:
                key = pl.get("project", "")
                L.append(f"  - [{key}] {projects.get(key, key)} - {pl.get('how', '')}")
        if a.get("reviewer_notes"):
            L.append("- **Reviewer's eye**:")
            L.extend(_fmt_list(a["reviewer_notes"]))
        if a.get("term_explanations"):
            L.append("- **Terms**:")
            for te in a["term_explanations"]:
                line = f"  - **{te.get('term', '')}**: {te.get('academic', '')}"
                if te.get("plain"):
                    line += f" | In plain words: {te['plain']}"
                L.append(line)
        if a.get("needs_verification"):
            L.append("- Needs verification: " + "; ".join(a["needs_verification"]))
        tail = []
        if a.get("action"):
            tail.append(f"Suggested action: {a['action']}")
        if a.get("tags"):
            tail.append("Tags: " + " ".join(f"#{t}" for t in a["tags"]))
        if tail:
            L.append("- " + " · ".join(tail))
        L.append("")

    groups = [("★★★ Must read", "★★★"), ("★★ Worth a look", "★★"), ("★ Skim", "★")]
    idx = 0
    for heading, tier in groups:
        sub = [a for a in arts if a["tier"] == tier]
        if not sub:
            continue
        if tier == "★★★":
            L.append(f"## {heading} (score >= {tiers.get('★★★', 85)})")
        elif tier == "★★":
            L.append(f"## {heading} (score {tiers.get('★★', 70)}-{float(tiers.get('★★★', 85)) - 1:g})")
        else:
            L.append(f"## {heading}")
        L.append("")
        for a in sub:
            idx += 1
            render_article(a, idx)

    if peripheral:
        L.append("## Peripheral scan (below the recommendation threshold, one line each)")
        L.append("")
        for p in peripheral[: int(review.get("max_peripheral", 10))]:
            L.append(f"- [{p.get('title', '')}]({p.get('url', '')}) · {p.get('venue', '')}" + (f" · {p.get('publication_date')}" if p.get("publication_date") else "") + (f" - {p['one_liner']}" if p.get("one_liner") else ""))
            if p.get("ecologist_summary"):
                L.append(f"  - {plain_label}: {p['ecologist_summary']}")
        L.append("")

    if rv.get("themes") or rv.get("continuity_notes"):
        L.append("## Theme pulse")
        L.append("")
        L += [f"- {t}" for t in rv.get("themes") or []]
        L += [f"- (continuity) {t}" for t in rv.get("continuity_notes") or []]
        L.append("")

    ideas = rv.get("research_ideas") or []
    if ideas:
        L.append("## Testable research ideas")
        L.append("")
        for i, idea in enumerate(ideas, 1):
            if isinstance(idea, str):
                L.append(f"{i}. {idea}")
            else:
                L.append(f"{i}. {idea.get('idea', '')}" + (f"  \n   How to test: {idea['testable_by']}" if idea.get("testable_by") else "") + (f"  \n   Related: {', '.join(idea['links'])}" if idea.get("links") else ""))
        L.append("")

    L.append("## Search log")
    L.append("")
    if srcs:
        for k, v in srcs.items():
            if v.get("status") == "disabled":
                continue
            L.append(f"- {k}: {v.get('count', 0)} records · {v.get('status')}" + (" (expanded window)" if v.get("expanded_window") else ""))
    if counts:
        L.append(f"- Deduplicated {counts.get('merged', '?')} · queued {counts.get('queue', '?')} · prescreen high-scoring {counts.get('high_score', '?')} · dropped as already delivered {counts.get('dropped_seen', 0)} · preprint-to-published updates {counts.get('preprint_to_published', 0)}")
    er = (meta or {}).get("excluded_reasons") or {}
    if er:
        L.append("- Excluded: " + "; ".join(f"{k} {v}" for k, v in er.items()))
    log_extra = rv.get("log") or {}
    for k, v in log_extra.items():
        if k not in ("sources", "counts"):
            L.append(f"- {k}: {v}")
    L.append("- Weights: " + " / ".join(f"{k} {float(v):.2f}" for k, v in weights.items()) + f" · threshold {review.get('recommendation_threshold', 70)} · ★★★ >= {tiers.get('★★★', 85)} · ★★ >= {tiers.get('★★', 70)}")
    L.append("")
    L.append(f"*lit-radar v{VERSION} · written by Claude after reading the evidence; preprints are not peer reviewed; all numbers should be checked against the original paper.*")
    return "\n".join(L) + "\n"


def find_run_meta(workdir: Path, rv: dict) -> dict | None:
    cand = []
    if rv.get("run_dir"):
        cand.append(Path(rv["run_dir"]) / "review_queue.json")
    if rv.get("date"):
        cand.append(workdir / "runs" / rv["date"] / "review_queue.json")
        for p in sorted((workdir / "runs").glob(f"{rv['date']}-*/review_queue.json")) if (workdir / "runs").exists() else []:
            cand.append(p)
    for p in cand:
        data = load_json(p, None)
        if data and data.get("meta"):
            return data["meta"]
    return None


def cmd_render(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    prof = load_profile(resolve_profile_path(workdir, args.profile))
    rv = load_json(Path(args.reviewed), None)
    if rv is None:
        raise SystemExit(f"reviewed file not found: {args.reviewed}")
    problems = validate_reviewed(rv, prof)
    if problems and not args.force:
        print("reviewed.json failed validation (fix the JSON; --force renders anyway):", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        return 3
    meta = find_run_meta(workdir, rv)
    md = render_report(rv, prof, meta)
    out = Path(args.out) if args.out else workdir / "runs" / (rv.get("date") or today().isoformat()) / "report.md"
    atomic_write_text(out, md)
    print(str(out))
    if problems:
        print("(warning: rendered with --force despite these problems)", file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
    return 0


# ----------------------------------------------------------------------------
# deliver: record delivery, BibTeX, optional push
# ----------------------------------------------------------------------------

def bibtex_for(a: dict) -> str:
    authors = a.get("authors") or []
    if not authors and a.get("authors_short"):
        authors = [a["authors_short"].replace(" et al.", "")]
    first = re.sub(r"[^A-Za-z]", "", (authors[0].split()[-1] if authors else "anon")) or "anon"
    year = (a.get("publication_date") or "n.d.")[:4]
    word = re.sub(r"[^A-Za-z]", "", (a.get("title", "").split() or ["paper"])[0]).lower() or "paper"
    key = f"{first.lower()}{year}{word}"
    kind = "misc" if a.get("is_preprint") else "article"
    fields = [("title", "{" + a.get("title", "") + "}"), ("author", " and ".join(authors) if authors else ""), ("year", year)]
    if not a.get("is_preprint"):
        fields.append(("journal", a.get("venue", "")))
    else:
        fields.append(("howpublished", a.get("venue", "")))
        fields.append(("note", "Preprint, not peer reviewed"))
    if a.get("doi"):
        fields.append(("doi", a["doi"]))
    if a.get("url"):
        fields.append(("url", a["url"]))
    body = ",\n".join(f"  {k} = {{{v}}}" if not v.startswith("{") else f"  {k} = {v}" for k, v in fields if v)
    return f"@{kind}{{{key},\n{body}\n}}\n"


def push_report(provider: str, title: str, markdown: str) -> str:
    provider = provider.lower()
    if provider == "none":
        return "not pushed"
    if provider == "wecom":
        url = os.environ.get("WECOM_WEBHOOK_URL") or os.environ.get("WECHAT_WORK_WEBHOOK_URL")
        if not url:
            return "WeCom not configured (WECOM_WEBHOOK_URL)"
        payload = {"msgtype": "markdown", "markdown": {"content": truncate(f"**{title}**\n" + markdown, 3900)}}
    elif provider == "serverchan":
        key = os.environ.get("SERVERCHAN_SENDKEY")
        if not key:
            return "ServerChan not configured (SERVERCHAN_SENDKEY)"
        url = f"https://sctapi.ftqq.com/{key}.send"
        payload = {"title": title, "desp": truncate(markdown, 30000)}
    elif provider == "webhook":
        url = os.environ.get("LIT_RADAR_WEBHOOK_URL")
        if not url:
            return "generic webhook not configured (LIT_RADAR_WEBHOOK_URL)"
        payload = {"title": title, "text": markdown}
    else:
        return f"unknown push provider: {provider}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": f"lit-radar/{VERSION}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        code = resp.status
    return f"pushed via {provider} (HTTP {code})"


def cmd_deliver(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    prof = load_profile(resolve_profile_path(workdir, args.profile))
    rv = load_json(Path(args.reviewed), None)
    if rv is None:
        raise SystemExit(f"reviewed file not found: {args.reviewed}")
    date = rv.get("date") or today().isoformat()
    meta = find_run_meta(workdir, rv)
    report_md = Path(args.report).read_text(encoding="utf-8") if args.report else render_report(rv, prof, meta)
    reports_dir = workdir / (prof.get("delivery", {}).get("report_dir") or "reports")
    suffix = f"-{rv['focus']}" if rv.get("focus") else ""
    report_path = reports_dir / f"lit-radar_{date}{suffix}.md"
    atomic_write_text(report_path, report_md)
    outputs = {"report": str(report_path)}

    arts = rv.get("articles") or []
    if (args.bibtex or prof.get("delivery", {}).get("bibtex")) and arts:
        bib_path = reports_dir / f"lit-radar_{date}{suffix}.bib"
        atomic_write_text(bib_path, "".join(bibtex_for(a) for a in arts))
        outputs["bibtex"] = str(bib_path)

    # dedup history: recommended and peripheral papers both count as shown
    seen = load_seen(workdir)
    papers = seen.setdefault("papers", {})
    weights = (prof.get("review") or {}).get("weights") or REVIEW_WEIGHTS
    for a in arts:
        aid = a.get("id") or canonical_id({"doi": norm_doi(a.get("doi")), "arxiv_id": a.get("arxiv_id"), "title": a.get("title", "")})
        papers[aid] = {"title": a.get("title"), "norm_title": norm_title(a.get("title", "")), "delivered": date,
                       "score": a.get("recommendation_score") or compute_score(a, weights), "tier": a.get("tier"),
                       "is_preprint": bool(a.get("is_preprint")), "venue": a.get("venue"), "doi": norm_doi(a.get("doi"))}
    for p in rv.get("peripheral") or []:
        pid = p.get("id") or canonical_id({"doi": norm_doi(p.get("doi")), "arxiv_id": p.get("arxiv_id"), "title": p.get("title", "")})
        papers.setdefault(pid, {"title": p.get("title"), "norm_title": norm_title(p.get("title", "")), "delivered": date,
                                "tier": "peripheral", "is_preprint": bool(p.get("is_preprint")), "venue": p.get("venue"), "doi": norm_doi(p.get("doi"))})
    seen["last_delivery"] = date
    atomic_write_json(seen_path(workdir), seen)

    # research memory
    if not args.no_memory:
        mem = load_memory(workdir)
        entry = {
            "date": date, "mode": rv.get("mode", "daily"), "focus": rv.get("focus"), "n_recommended": len(arts),
            "top": [{"id": a.get("id"), "title": a.get("title"), "score": a.get("recommendation_score") or compute_score(a, weights),
                     "tags": a.get("tags", [])[:6], "projects": [pl.get("project") for pl in a.get("project_links", []) if pl.get("project")],
                     "strong": bool(a.get("strong_recommendation"))} for a in arts[:6]],
            "themes": rv.get("themes", [])[:6],
            "research_ideas": [i if isinstance(i, str) else i.get("idea", "") for i in rv.get("research_ideas", [])][:5],
            "open_verification": [f"{truncate(a.get('title', ''), 60)}: {'; '.join(a['needs_verification'])}" for a in arts if a.get("needs_verification")][:5],
            "continuity_notes": rv.get("continuity_notes", [])[:4],
        }
        mem.setdefault("entries", []).append(entry)
        mem["entries"] = mem["entries"][-120:]
        tc = mem.setdefault("tag_counts", {})
        pc = mem.setdefault("project_counts", {})
        for a in arts:
            for t in a.get("tags", []):
                tc[t] = tc.get(t, 0) + 1
            for pl in a.get("project_links", []):
                if pl.get("project"):
                    pc[pl["project"]] = pc.get(pl["project"], 0) + 1
        atomic_write_json(memory_path(workdir), mem)
        outputs["memory_entries"] = len(mem["entries"])

    push_status = "not pushed"
    if args.push and args.push != "none":
        try:
            push_status = push_report(args.push, f"Literature Radar {date}", report_md)
        except Exception as exc:
            push_status = f"push failed: {type(exc).__name__}: {truncate(str(exc), 200)}"
    outputs["push"] = push_status
    outputs["seen_total"] = len(papers)
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


# ----------------------------------------------------------------------------
# status / init / selftest
# ----------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    prof_path = resolve_profile_path(workdir, args.profile)
    seen = load_seen(workdir)
    mem = load_memory(workdir)
    runs = sorted(p.name for p in (workdir / "runs").glob("*")) if (workdir / "runs").exists() else []
    reports = sorted(p.name for p in (workdir / "reports").glob("*.md")) if (workdir / "reports").exists() else []
    info = {
        "version": VERSION, "skill_dir": str(SKILL_DIR), "workdir": str(workdir), "profile": str(prof_path),
        "profile_exists": prof_path.exists(), "topics": str(resolve_topics_path(workdir)),
        "seen_papers": len(seen.get("papers", {})), "last_delivery": seen.get("last_delivery"),
        "memory_entries": len(mem.get("entries", [])), "runs": runs[-7:], "reports": reports[-7:],
        "env": {k: ("set" if os.environ.get(k) else "unset") for k in ("LIT_RADAR_HOME", "OPENALEX_MAILTO", "OPENALEX_API_KEY", "S2_API_KEY", "WECOM_WEBHOOK_URL", "SERVERCHAN_SENDKEY", "LIT_RADAR_WEBHOOK_URL")},
    }
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    workdir = resolve_workdir(args.workdir)
    dst = workdir / "config"
    dst.mkdir(parents=True, exist_ok=True)
    if args.example:
        srcs = [EXAMPLES_DIR / f"{args.example}.json", EXAMPLES_DIR / f"{args.example}.md"]
        if not srcs[0].exists():
            available = ", ".join(p.stem for p in EXAMPLES_DIR.glob("*.json")) or "(none)"
            raise SystemExit(f"unknown example {args.example!r}; available: {available}")
    else:
        srcs = [DEFAULT_PROFILE, DEFAULT_TOPICS]
    targets = [dst / "research_profile.json", dst / "research_topics.md"]
    copied = []
    for src, target in zip(srcs, targets):
        if target.exists() and not args.force:
            log(f"  exists, skipped: {target} (use --force to overwrite)")
            continue
        shutil.copyfile(src, target)
        copied.append(str(target))
    for sub_dir in ("data", "runs", "reports"):
        (workdir / sub_dir).mkdir(parents=True, exist_ok=True)
    note = ("Template copied: fill in research_profile.json and research_topics.md, then set configured to true."
            if not args.example else f"Example '{args.example}' copied: edit active_projects, queries and topic_groups to match your programme.")
    print(json.dumps({"workdir": str(workdir), "copied": copied, "note": note}, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Offline end-to-end: fixture -> collect -> auto-generated example reviewed.json -> render -> deliver (into a temp dir)."""
    tmp = Path(args.workdir).expanduser() if args.workdir else Path(tempfile.mkdtemp(prefix="lit-radar-selftest-"))
    prof_path = Path(args.profile) if args.profile else (DEFAULT_PROFILE if (load_json(DEFAULT_PROFILE, {}) or {}).get("configured") else EXAMPLE_PROFILE)
    prof = load_profile(prof_path)
    ns = argparse.Namespace(workdir=str(tmp), profile=str(prof_path), mode="daily", days=None, since=None, until=None,
                            focus=None, topic=None, offline=str(FIXTURE), min_score=None, max_queue=None,
                            include_seen=False, tag=None)
    rc = cmd_collect(ns)
    if rc != 0:
        return rc
    run_dir = tmp / "runs" / today().isoformat()
    rq = load_json(run_dir / "review_queue.json", {})
    cands = rq.get("candidates", [])
    articles, peripheral = [], []
    eco = ("EXAMPLE TEXT (fictional paper). In one paragraph a general ecologist can follow: what question the study asks, "
           "what system or model it uses, what it found, and why the finding matters for how we think about species coexistence "
           "and community stability. The real report replaces this with a paper-specific explanation of 80-160 words.")
    for c in cands:
        sc = c["prescreen"]["score"]
        if sc >= 70 and len(articles) < 3:
            rel = min(100, int(sc))
            comp = {"relevance": rel, "novelty": 78, "quality": 80, "methodology": 82, "inspiration": 75}
            articles.append({
                "id": c["id"], "title": c["title"], "authors": c.get("authors", []),
                "authors_short": (c.get("authors") or ["Anon"])[0] + (" et al." if len(c.get("authors") or []) > 1 else ""),
                "venue": c.get("venue"), "publication_date": c.get("published_date"), "doi": c.get("doi"), "arxiv_id": c.get("arxiv_id"),
                "url": c.get("url"), "article_type": "Preprint" if c.get("is_preprint") else "Research article", "is_preprint": c.get("is_preprint"),
                "score_status": "evidence_reviewed", "component_scores": comp,
                "why_worth_reading": "Example: filled in automatically by selftest to exercise rendering and delivery.",
                "ecologist_summary": eco,
                "core_findings": ["Example finding 1 (fictional)", "Example finding 2 (fictional)", "Example finding 3 (fictional)"],
                "project_links": [{"project": (prof.get("active_projects") or [{"key": "demo"}])[0]["key"], "how": "example link"}],
                "reviewer_notes": ["Example: sample size / model assumptions need verification"],
                "term_explanations": [{"term": "example term", "academic": "rigorous definition (example)", "plain": "plain-words version (example)"}],
                "tags": [k.lower().replace(" & ", "-").replace(" ", "-").replace("/", "-") for k in list(c["prescreen"]["hits"].keys())[:3]], "action": "skim",
            })
        elif len(peripheral) < 5:
            peripheral.append({"id": c["id"], "title": c["title"], "venue": c.get("venue"), "url": c.get("url"), "publication_date": c.get("published_date"), "one_liner": "example one-liner (fictional)"})
    rv = {"date": today().isoformat(), "mode": "daily", "fixture": True, "run_dir": str(run_dir),
          "summary": {"headline": "selftest example: the pipeline works.", "signal": "This report is built from fictional data and only checks the format.",
                      "top3": [{"title": a["title"], "reason": "example reason"} for a in articles[:3]]},
          "articles": articles, "peripheral": peripheral, "themes": ["example theme A", "example theme B"],
          "continuity_notes": [], "research_ideas": [{"idea": "example research idea (fictional)", "testable_by": "example test"}]}
    rv_path = run_dir / "reviewed.json"
    atomic_write_json(rv_path, rv)
    problems = validate_reviewed(rv, prof)
    if problems:
        print("selftest: reviewed validation problems:", problems, file=sys.stderr)
        return 4
    md = render_report(rv, prof, rq.get("meta"))
    atomic_write_text(run_dir / "report.md", md)
    ns2 = argparse.Namespace(workdir=str(tmp), profile=str(prof_path), reviewed=str(rv_path), report=str(run_dir / "report.md"),
                             bibtex=True, push="none", no_memory=False)
    cmd_deliver(ns2)
    print(f"\nselftest passed. Work directory: {tmp}\nExample report: {run_dir / 'report.md'}")
    if args.show:
        print("\n" + md)
    return 0


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lit_radar.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"lit-radar {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--workdir", help="work directory (data / runs / reports). Default: $LIT_RADAR_HOME or ./lit-radar")
        sp.add_argument("--profile", help="path to the research profile JSON (default: <workdir>/config/ or the skill's bundled copy)")

    sp = sub.add_parser("init", help="copy the configuration template (or a worked example) into the work directory for editing")
    common(sp)
    sp.add_argument("--example", help="copy config/examples/<name>.json+.md instead of the blank template (e.g. theoretical-ecology)")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    for name, fn, helptext in (("collect", cmd_collect, "search the sources and build the review queue"), ("queries", cmd_queries, "print the search plan"),
                               ("plan", cmd_plan, "write small-page API URLs for the WebFetch bridge (sandbox without egress)")):
        sp = sub.add_parser(name, help=helptext)
        common(sp)
        sp.add_argument("--mode", choices=["daily", "weekly", "catchup"], default="daily")
        sp.add_argument("--focus", help="named focus mode (see focus_modes in the profile)")
        sp.add_argument("--topic", help="append one ad-hoc free-text query")
        sp.add_argument("--days", type=int, help="override the window length in days")
        sp.add_argument("--since", help="window start YYYY-MM-DD")
        sp.add_argument("--until", help="window end YYYY-MM-DD (default: today)")
        if name == "plan":
            sp.add_argument("--per-page", dest="per_page", default=25, help="records per API page (keep small so WebFetch does not truncate)")
        if name == "collect":
            sp.add_argument("--offline", help="use a fixture JSON instead of the network (testing)")
            sp.add_argument("--records", help="ingest records collected through the WebFetch bridge (see `plan`) instead of calling the APIs")
            sp.add_argument("--min-score", type=float, dest="min_score", help="minimum prescreen score to enter the queue")
            sp.add_argument("--max-queue", type=int, dest="max_queue")
            sp.add_argument("--include-seen", action="store_true", dest="include_seen", help="do not drop previously delivered papers")
            sp.add_argument("--tag", help="suffix for the run directory to avoid overwriting a same-day run")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("memory", help="print the research memory")
    common(sp)
    sp.add_argument("--last", type=int, default=10)
    sp.set_defaults(func=cmd_memory)

    sp = sub.add_parser("render", help="reviewed.json -> Markdown report")
    common(sp)
    sp.add_argument("--reviewed", required=True)
    sp.add_argument("--out")
    sp.add_argument("--force", action="store_true", help="render even if validation fails")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("deliver", help="record delivery and optionally push")
    common(sp)
    sp.add_argument("--reviewed", required=True)
    sp.add_argument("--report", help="already rendered Markdown (re-rendered if omitted)")
    sp.add_argument("--bibtex", action="store_true")
    sp.add_argument("--push", choices=["none", "wecom", "serverchan", "webhook"], default="none")
    sp.add_argument("--no-memory", action="store_true", dest="no_memory")
    sp.set_defaults(func=cmd_deliver)

    sp = sub.add_parser("status", help="show status")
    common(sp)
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("selftest", help="run the whole pipeline offline")
    common(sp)
    sp.add_argument("--show", action="store_true", help="print the example report to stdout")
    sp.set_defaults(func=cmd_selftest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
