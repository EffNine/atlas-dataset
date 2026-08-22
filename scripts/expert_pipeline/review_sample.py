"""Human review calibration sample generation for the 6500 pilot.

Per docs/specialist_10k_pilot_extraction_plan_v0.1.md §5:
- path: review/expert_pilot_6500_review_sample_v0.1.jsonl
- stratified sample, target ~5% (~325 records) for human gate calibration

Stratification (deterministic, seeded):
1. proportional to source composition (500/3000/3000 -> 25/150/150)
2. within each source, proportional across quality bands (5-6 / 7-8 / 9-10)

Proportional review policy (--domain-rates): per-domain sample rates allow
risk-proportional human verification (e.g. heavier sampling for domains
without machine-verifiable answers such as architecture design docs or
agentic traces, lighter sampling for execution-verified code). When omitted,
the flat default rate applies and output is unchanged.

Each sample line = the full Atlas expert record plus a review envelope
(review_id, record_id, stratum, pending state, calibration context).
The pipeline never writes approval decisions; dataset stays read-only.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECORDS = REPO_ROOT / "tmp" / "expert_pilot_6500_records_v0.1.jsonl"
DEFAULT_SAMPLE = REPO_ROOT / "review" / "expert_pilot_6500_review_sample_v0.1.jsonl"

QUALITY_BANDS = [(5, 6), (7, 8), (9, 10)]
SAMPLE_RATE = 0.05
SEED = 20260802


def _band(score: int) -> tuple[int, int]:
    for lo, hi in QUALITY_BANDS:
        if lo <= score <= hi:
            return (lo, hi)
    return (0, 4)


def load_records(path: Path) -> list[dict]:
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def resolve_rate(domain: str | None, base_rate: float,
                 domain_rates: dict[str, float] | None) -> float:
    """Effective sample rate for one stratum's domain."""
    if domain_rates and domain is not None and domain in domain_rates:
        return domain_rates[domain]
    return base_rate


def stratify(records: list[dict], rate: float = SAMPLE_RATE, seed: int = SEED,
             domain_rates: dict[str, float] | None = None):
    """Return sampled records with a 'stratum' key, deterministic by seed."""
    # group by source -> quality band
    buckets: dict[tuple[str, tuple[int, int]], list[dict]] = defaultdict(list)
    for r in records:
        buckets[(r["source"]["source_id"], _band(r["metadata"]["quality_score"]))].append(r)

    rng = random.Random(seed)
    for key, group in buckets.items():
        eff_rate = resolve_rate(group[0].get("domain"), rate, domain_rates)
        n = round(len(group) * eff_rate)
        if eff_rate > 0:
            n = max(1, n)
        # deterministic shuffle per stratum
        idx = list(range(len(group)))
        rng.shuffle(idx)
        for i in idx[:n]:
            picked = group[i]
            picked = dict(picked)
            picked["stratum"] = {
                "source_id": key[0],
                "quality_band": list(key[1]),
                "sample_rate": eff_rate,
            }
            yield picked


def build_sample(records: list[dict], rate: float = SAMPLE_RATE, seed: int = SEED,
                 domain_rates: dict[str, float] | None = None) -> list[dict]:
    sampled = list(stratify(records, rate=rate, seed=seed, domain_rates=domain_rates))
    # stable ordering for review: by source, then original id
    sampled.sort(key=lambda r: (r["source"]["source_id"], r["id"]))
    out = []
    for i, rec in enumerate(sampled, start=1):
        out.append({
            "review_id": f"rev_{i:06d}",
            "record_id": rec["id"],
            "source_id": rec["source"]["source_id"],
            "stratum": rec["stratum"],
            "review_status": "pending",
            "assigned_reviewer": None,
            "assigned_timestamp": None,
            "completed_timestamp": None,
            "calibration": {
                "auto_gate": "KEEP",  # computed at generation; gate calibrates against human verdict
                "quality_score": rec["metadata"]["quality_score"],
                "difficulty": rec["difficulty"],
                "expert_tier": rec["expert_tier"],
            },
            "record": {k: v for k, v in rec.items() if k != "stratum"},
        })
    return out


def write_sample(sample: list[dict], path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing review sample: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for entry in sample:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def summarize(sample: list[dict]) -> dict:
    by_src = Counter(e["source_id"] for e in sample)
    by_band = Counter(tuple(e["stratum"]["quality_band"]) for e in sample)
    return {
        "total": len(sample),
        "per_source": dict(sorted(by_src.items())),
        "per_quality_band": {f"{lo}-{hi}": by_band.get((lo, hi), 0) for lo, hi in QUALITY_BANDS},
        "review_status_counts": dict(Counter(e["review_status"] for e in sample)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate 6500-pilot human review sample")
    parser.add_argument("--records", default=str(DEFAULT_RECORDS))
    parser.add_argument("--output", default=str(DEFAULT_SAMPLE))
    parser.add_argument("--rate", type=float, default=SAMPLE_RATE, help="sample rate (default 0.05)")
    parser.add_argument("--domain-rates", default=None,
                        help="JSON map of domain -> sample rate overriding --rate "
                             "(e.g. '{\"software_engineering\": 0.2}')")
    parser.add_argument("--seed", type=int, default=SEED, help="deterministic seed (default 20260802)")
    args = parser.parse_args(argv)

    domain_rates = None
    if args.domain_rates:
        try:
            domain_rates = json.loads(args.domain_rates)
        except ValueError:
            parser.error("--domain-rates must be valid JSON, e.g. '{\"mathematics\": 0.1}'")
        if not isinstance(domain_rates, dict) or not all(
                isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in domain_rates.values()):
            parser.error("--domain-rates values must be numbers in [0.0, 1.0]")

    records = load_records(Path(args.records))
    sample = build_sample(records, rate=args.rate, seed=args.seed, domain_rates=domain_rates)
    out = Path(args.output)
    write_sample(sample, out)
    print(json.dumps({"written": str(out), "sample_size": len(sample),
                      "per_source": summarize(sample)["per_source"],
                      "per_quality_band": summarize(sample)["per_quality_band"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
