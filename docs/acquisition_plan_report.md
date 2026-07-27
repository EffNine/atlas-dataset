# Atlas Acquisition Engine — Pre-Ingestion Report

**Generated:** 2026-07-27T12:03:24.535346+00:00
**Mode:** DRY-RUN
**Manifest version:** 0.1.0

## 1. Executive Summary

- Sources planned: **38**
- Batches planned: **9**
- Target examples: **1000**
- Estimated download: **3.1 TB**
- License gate: **PASS**
- Synthetic: **37 (3.7%)** cap=5% ✅ within cap
- Registry: **OK**
- Category balance: **OK**
- Pilot already exists: **5 records**

## 2. License Validation

| Source | License | Class | Denied? |
|---|---|---|---|

## 3. Execution Plan

### B01 (order 1) — Foundation SFT seed (verified, permissive)

- `resolve:f1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:f1`: download to raw/01_foundation/f1/ (est 100.7 MB)
- `pipeline:f1`: clean -> dedup -> convert -> quality_score
- `gate:f1`: apply quality_gate (score>=7); human review -> verified
- `resolve:f6`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:f6`: download to raw/01_foundation/f6/ (est 28.6 MB)
- `pipeline:f6`: clean -> dedup -> convert -> quality_score
- `gate:f6`: apply quality_gate (score>=7); human review -> verified
- `resolve:f5`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:f5`: download to raw/01_foundation/f5/ (est 762.9 MB)
- `pipeline:f5`: clean -> dedup -> convert -> quality_score
- `gate:f5`: apply quality_gate (score>=7); human review -> verified
- `resolve:f2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:f2`: download to raw/01_foundation/f2/ (est 15.3 MB)
- `constraint:f2`: gated: accept HF terms; re-verify license on download; record date_added in sources.json
- `pipeline:f2`: clean -> dedup -> convert -> quality_score
- `gate:f2`: apply quality_gate (score>=7); human review -> verified

### B02 (order 2) — Software engineering (verified + community)

- `resolve:s1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:s1`: download to raw/02_software_engineering/s1/ (est 397.2 MB)
- `pipeline:s1`: clean -> dedup -> convert -> quality_score
- `gate:s1`: apply quality_gate (score>=7); human review -> verified
- `resolve:s4`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:s4`: download to raw/02_software_engineering/s4/ (est 38.1 MB)
- `pipeline:s4`: clean -> dedup -> convert -> quality_score
- `gate:s4`: apply quality_gate (score>=7); human review -> verified
- `resolve:s6`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:s6`: download to raw/02_software_engineering/s6/ (est 1.9 GB)
- `constraint:s6`: audit per-subset licenses; exclude any NC/restricted sub-component
- `pipeline:s6`: clean -> dedup -> convert -> quality_score
- `gate:s6`: apply quality_gate (score>=7); human review -> verified
- `resolve:s5`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:s5`: download to raw/02_software_engineering/s5/ (est 55.9 GB)
- `constraint:s5`: attribution per record (post id + author + URL)
- `constraint:s5`: share-alike tracking in source.license
- `constraint:s5`: filter score>=5
- `constraint:s5`: strip PII
- `pipeline:s5`: clean -> dedup -> convert -> quality_score
- `gate:s5`: apply quality_gate (score>=7); human review -> verified
- `resolve:s2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:s2`: download to raw/02_software_engineering/s2/ (est 2.7 TB)
- `constraint:s2`: subset to per-file permissive licenses only
- `constraint:s2`: document RAIL-M behavioral use clauses
- `constraint:s2`: record RAIL-M obligations in ingestion runbook
- `pipeline:s2`: clean -> dedup -> convert -> quality_score
- `gate:s2`: apply quality_gate (score>=7); human review -> verified

### B03 (order 3) — System engineering (Tier-1 docs + community)

- `resolve:y1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:y1`: download to raw/03_system_engineering/y1/ (est 476.8 MB)
- `constraint:y1`: pin doc version; flag any GFDL subsections for separate tracking
- `pipeline:y1`: clean -> dedup -> convert -> quality_score
- `gate:y1`: apply quality_gate (score>=7); human review -> verified
- `resolve:y2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:y2`: download to raw/03_system_engineering/y2/ (est 286.1 MB)
- `constraint:y2`: pin doc version
- `pipeline:y2`: clean -> dedup -> convert -> quality_score
- `gate:y2`: apply quality_gate (score>=7); human review -> verified
- `resolve:y3`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:y3`: download to raw/03_system_engineering/y3/ (est 190.7 MB)
- `constraint:y3`: pin doc version
- `pipeline:y3`: clean -> dedup -> convert -> quality_score
- `gate:y3`: apply quality_gate (score>=7); human review -> verified
- `resolve:y4`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:y4`: download to raw/03_system_engineering/y4/ (est 381.5 MB)
- `constraint:y4`: attribution per article
- `constraint:y4`: share-alike tracking
- `constraint:y4`: restructure wiki tone to task format
- `pipeline:y4`: clean -> dedup -> convert -> quality_score
- `gate:y4`: apply quality_gate (score>=7); human review -> verified
- `resolve:y5`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:y5`: download to raw/03_system_engineering/y5/ (est 74.5 GB)
- `constraint:y5`: attribution per record
- `constraint:y5`: share-alike tracking
- `constraint:y5`: filter score>=5
- `constraint:y5`: strip PII
- `pipeline:y5`: clean -> dedup -> convert -> quality_score
- `gate:y5`: apply quality_gate (score>=7); human review -> verified

### B04 (order 4) — AI & ML (Tier-1 + verified open)

- `resolve:m1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:m1`: download to raw/04_ai_machine_learning/m1/ (est 46.6 GB)
- `constraint:m1`: convert only well-sourced sections
- `constraint:m1`: cite arXiv id
- `constraint:m1`: flag preprint status
- `pipeline:m1`: clean -> dedup -> convert -> quality_score
- `gate:m1`: apply quality_gate (score>=7); human review -> verified
- `resolve:m2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:m2`: download to raw/04_ai_machine_learning/m2/ (est 114.4 MB)
- `pipeline:m2`: clean -> dedup -> convert -> quality_score
- `gate:m2`: apply quality_gate (score>=7); human review -> verified
- `resolve:m3`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:m3`: download to raw/04_ai_machine_learning/m3/ (est 953.7 MB)
- `constraint:m3`: audit per-subset licenses; exclude NC/restricted
- `pipeline:m3`: clean -> dedup -> convert -> quality_score
- `gate:m3`: apply quality_gate (score>=7); human review -> verified
- `resolve:m4`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:m4`: download to raw/04_ai_machine_learning/m4/ (est 93.1 GB)
- `constraint:m4`: subset ONLY to permissive components (arXiv, PubMed, FreeLaw, etc.)
- `constraint:m4`: exclude restricted subsets
- `constraint:m4`: per-record license tagging
- `pipeline:m4`: clean -> dedup -> convert -> quality_score
- `gate:m4`: apply quality_gate (score>=7); human review -> verified

### B05 (order 5) — Science & engineering (verified benchmarks + open)

- `resolve:c1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:c1`: download to raw/06_science_engineering/c1/ (est 4.5 MB)
- `constraint:c1`: reserve official test split as EVAL (do not SFT the test split)
- `pipeline:c1`: clean -> dedup -> convert -> quality_score
- `gate:c1`: apply quality_gate (score>=7); human review -> verified
- `resolve:c2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:c2`: download to raw/06_science_engineering/c2/ (est 161.0 MB)
- `constraint:c2`: reserve official test split as EVAL
- `constraint:c2`: convert MC to open-form for SFT
- `pipeline:c2`: clean -> dedup -> convert -> quality_score
- `gate:c2`: apply quality_gate (score>=7); human review -> verified
- `resolve:c3`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:c3`: download to raw/06_science_engineering/c3/ (est 114.4 MB)
- `pipeline:c3`: clean -> dedup -> convert -> quality_score
- `gate:c3`: apply quality_gate (score>=7); human review -> verified
- `resolve:c5`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:c5`: download to raw/06_science_engineering/c5/ (est 52.8 GB)
- `pipeline:c5`: clean -> dedup -> convert -> quality_score
- `gate:c5`: apply quality_gate (score>=7); human review -> verified
- `resolve:c6`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:c6`: download to raw/06_science_engineering/c6/ (est 19.1 MB)
- `pipeline:c6`: clean -> dedup -> convert -> quality_score
- `gate:c6`: apply quality_gate (score>=7); human review -> verified

### B06 (order 6) — Hardware (licensed + capped synthetic)

- `resolve:h2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:h2`: download to raw/05_hardware_engineering/h2/ (est 4.7 GB)
- `constraint:h2`: convert only well-sourced sections
- `constraint:h2`: cite arXiv id
- `pipeline:h2`: clean -> dedup -> convert -> quality_score
- `gate:h2`: apply quality_gate (score>=7); human review -> verified
- `resolve:h1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:h1`: download to raw/05_hardware_engineering/h1/ (est 286.1 MB)
- `constraint:h1`: attribution per article
- `constraint:h1`: share-alike tracking
- `pipeline:h1`: clean -> dedup -> convert -> quality_score
- `gate:h1`: apply quality_gate (score>=7); human review -> verified
- `resolve:h4`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:h4`: download to raw/05_hardware_engineering/h4/ (est 18.6 GB)
- `constraint:h4`: attribution per record
- `constraint:h4`: filter score>=5
- `constraint:h4`: strip PII
- `pipeline:h4`: clean -> dedup -> convert -> quality_score
- `gate:h4`: apply quality_gate (score>=7); human review -> verified
- `resolve:h6`: resolve source_id -> registry; confirm status in (accepted,review)
- `generate:h6`: generate locally from licensed docs (no download)
- `constraint:h6`: capped <=15% of hardware category (<=12)
- `constraint:h6`: only from licensed docs h1/h2/h4
- `constraint:h6`: every record human-reviewed before curated/
- `pipeline:h6`: clean -> dedup -> convert -> quality_score
- `gate:h6`: apply quality_gate (score>=7); human review -> verified
- `resolve:h3`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:h3`: download to raw/05_hardware_engineering/h3/ (est 190.7 MB)
- `constraint:h3`: RE-VERIFY license on access
- `constraint:h3`: attribution per article
- `constraint:h3`: share-alike tracking
- `pipeline:h3`: clean -> dedup -> convert -> quality_score
- `gate:h3`: apply quality_gate (score>=7); human review -> verified

### B07 (order 7) — Business (licensed + capped synthetic)

- `resolve:b1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:b1`: download to raw/07_business_knowledge/b1/ (est 76.3 MB)
- `pipeline:b1`: clean -> dedup -> convert -> quality_score
- `gate:b1`: apply quality_gate (score>=7); human review -> verified
- `resolve:b3`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:b3`: download to raw/07_business_knowledge/b3/ (est 9.3 GB)
- `constraint:b3`: attribution per record
- `constraint:b3`: filter score>=5
- `constraint:b3`: strip PII
- `pipeline:b3`: clean -> dedup -> convert -> quality_score
- `gate:b3`: apply quality_gate (score>=7); human review -> verified
- `resolve:b2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:b2`: download to raw/07_business_knowledge/b2/ (est 286.1 MB)
- `constraint:b2`: attribution per article
- `constraint:b2`: share-alike tracking
- `pipeline:b2`: clean -> dedup -> convert -> quality_score
- `gate:b2`: apply quality_gate (score>=7); human review -> verified
- `resolve:b4`: resolve source_id -> registry; confirm status in (accepted,review)
- `generate:b4`: generate locally from licensed docs (no download)
- `constraint:b4`: capped <=15% of business category (<=10)
- `constraint:b4`: only from licensed docs b1/b2
- `constraint:b4`: every record human-reviewed
- `pipeline:b4`: clean -> dedup -> convert -> quality_score
- `gate:b4`: apply quality_gate (score>=7); human review -> verified

### B08 (order 8) — Creative (licensed PD + capped synthetic)

- `resolve:r1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:r1`: download to raw/08_creative_knowledge/r1/ (est 9.3 GB)
- `pipeline:r1`: clean -> dedup -> convert -> quality_score
- `gate:r1`: apply quality_gate (score>=7); human review -> verified
- `resolve:r2`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:r2`: download to raw/08_creative_knowledge/r2/ (est 286.1 MB)
- `constraint:r2`: attribution per article
- `constraint:r2`: share-alike tracking
- `pipeline:r2`: clean -> dedup -> convert -> quality_score
- `gate:r2`: apply quality_gate (score>=7); human review -> verified
- `resolve:r3`: resolve source_id -> registry; confirm status in (accepted,review)
- `generate:r3`: generate locally from licensed docs (no download)
- `constraint:r3`: capped <=20% of creative category (<=10)
- `constraint:r3`: only from PD/Gutenberg style text
- `constraint:r3`: every record human-reviewed
- `pipeline:r3`: clean -> dedup -> convert -> quality_score
- `gate:r3`: apply quality_gate (score>=7); human review -> verified

### B09 (order 9) — Personal assistant (derived + capped synthetic)

- `resolve:f1`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:f1`: download to raw/09_personal_assistant/f1/ (est 100.7 MB)
- `constraint:f1`: sub-filter: planning / productivity / workflow turns only
- `pipeline:f1`: clean -> dedup -> convert -> quality_score
- `gate:f1`: apply quality_gate (score>=7); human review -> verified
- `resolve:s6`: resolve source_id -> registry; confirm status in (accepted,review)
- `download:s6`: download to raw/09_personal_assistant/s6/ (est 1.9 GB)
- `constraint:s6`: sub-filter: planning / agentic / decision-making
- `pipeline:s6`: clean -> dedup -> convert -> quality_score
- `gate:s6`: apply quality_gate (score>=7); human review -> verified
- `resolve:g1`: resolve source_id -> registry; confirm status in (accepted,review)
- `generate:g1`: generate locally from licensed docs (no download)
- `constraint:g1`: capped <=20% of 09 category (<=10)
- `constraint:g1`: only from licensed planning docs
- `constraint:g1`: every record human-reviewed
- `pipeline:g1`: clean -> dedup -> convert -> quality_score
- `gate:g1`: apply quality_gate (score>=7); human review -> verified

## 4. Next Step

Run with `--execute` to begin ingestion. Use `--resume` to continue from an interrupted run.

> **DRY RUN — no data downloaded, transformed, or written outside metadata/docs.**

