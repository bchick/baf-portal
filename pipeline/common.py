"""Shared helpers: paths, cached rate-limited HTTP, gene list."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
CURATED = ROOT / "data" / "curated"
SITE_DATA = ROOT / "site" / "public" / "data"

def _curated_genes() -> dict[str, str]:
    """HGNC symbol -> UniProt canonical accession for every curated subunit
    (data/curated/composition.yaml is the single source of truth).
    BAF_GENES=SMARCA4,PBRM1 restricts a build to those genes."""
    import yaml
    subs = yaml.safe_load(open(CURATED / "composition.yaml"))["subunits"]
    genes = {s["symbol"]: s["uniprot"] for s in subs}
    only = [g.strip() for g in os.environ.get("BAF_GENES", "").split(",") if g.strip()]
    if only:
        unknown = set(only) - set(genes)
        if unknown:
            raise SystemExit(f"BAF_GENES: not curated subunits: {sorted(unknown)}")
        genes = {g: genes[g] for g in only}
    return genes


GENES = _curated_genes()

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 baf-portal/0.1"
)

_session = requests.Session()
_session.headers["User-Agent"] = BROWSER_UA
_last_call: dict[str, float] = {}

# Minimum seconds between calls per host. NCBI allows 3/s without a key.
MIN_INTERVAL = {
    "eutils.ncbi.nlm.nih.gov": 0.36,
    "rest.ensembl.org": 0.08,
    "grch37.rest.ensembl.org": 0.08,
    "www.cbioportal.org": 0.1,
}


def _throttle(host: str) -> None:
    gap = MIN_INTERVAL.get(host, 0.05)
    wait = _last_call.get(host, 0) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.monotonic()


def refreshing(cache_dir: str) -> bool:
    """BAF_REFRESH=1 (or 'all') ignores every cache; a comma list such as
    'clinvar,cbioportal' refreshes only those cache directories (the weekly CI
    build refreshes sources that change and keeps deterministic VEP results)."""
    v = os.environ.get("BAF_REFRESH", "").strip()
    if v in ("", "0"):
        return False
    return v in ("1", "all") or cache_dir in {x.strip() for x in v.split(",")}


def _key(method: str, url: str, params, body) -> str:
    blob = json.dumps([method, url, params, body], sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def fetch(url: str, *, params=None, json_body=None, data=None, method="GET",
          headers=None, cache_dir: str = "http", as_json=True, refresh=False,
          retries: int = 5):
    """HTTP with on-disk gzip cache in data/cache/<cache_dir>/ and per-host throttling."""
    body = json_body if json_body is not None else data
    path = CACHE / cache_dir / (_key(method, url, params, body) + (".json.gz" if as_json else ".txt.gz"))
    if path.exists() and not refresh and not refreshing(cache_dir):
        with gzip.open(path, "rt") as fh:
            txt = fh.read()
        return json.loads(txt) if as_json else txt
    host = url.split("/")[2]
    h = {"Accept": "application/json"} if as_json else {}
    h.update(headers or {})
    for attempt in range(retries):
        _throttle(host)
        try:
            r = _session.request(method, url, params=params, json=json_body, data=data,
                                 headers=h, timeout=120)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
            continue
        r.raise_for_status()
        txt = r.text
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt") as fh:
            fh.write(txt)
        return json.loads(txt) if as_json else txt
    raise RuntimeError(f"failed after {retries} attempts: {method} {url} {params}")


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def write_json(path: Path, obj, *, compact=True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        if compact:
            json.dump(obj, fh, separators=(",", ":"), ensure_ascii=False)
        else:
            json.dump(obj, fh, indent=1, ensure_ascii=False)
