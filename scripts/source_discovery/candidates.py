"""Initial candidate inventory for Source Discovery v1.0.

Honesty contract: nothing here is claimed verified until verify.py confirms it
live (HF Hub API / HTTP HEAD). Sizes, licenses, and formats below are
best-effort discovery notes labeled UNVERIFIED where appropriate — never
fabricated as ground truth. Verification overwrites these fields with
evidence or marks the source accordingly.
"""

from __future__ import annotations

from typing import Any

from .registry import blank_entry, refresh_license_state


def _e(source_id: str, **kw: Any) -> dict[str, Any]:
    entry = blank_entry(source_id)
    entry.update(kw)
    return refresh_license_state(entry)


def build_initial_candidates() -> list[dict[str, Any]]:
    c: list[dict[str, Any]] = []

    c.append(_e(
        "opus-100", name="Helsinki-NLP OPUS-100",
        source_type="parallel_corpus",
        languages=["zh", "ja", "ko", "ms", "en"],
        directions=["zh→en", "ja→en", "ko→en", "ms→en"],
        url="https://huggingface.co/datasets/Helsinki-NLP/opus-100",
        repo_id="Helsinki-NLP/opus-100",
        license="UNKNOWN",
        license_evidence="OPUS mixed upstream licenses (OpenSubtitles-derived). "
            "translation-ai-v0.1 records research/baseline-only local use, no "
            "redistribution. Per-sentence rights UNVERIFIED — resolve before "
            "any training-ready claim.",
        publisher="Helsinki-NLP / OPUS",
        citation="Zhang et al. 2020 (OPUS-100). DOI UNVERIFIED.",
        estimated_size="UNVERIFIED — ~1M pairs per en-xx config claimed in "
            "literature; confirm live via Hub API row counts.",
        format="Hugging Face datasets (translation dict)",
        access_method="huggingface: load_dataset streaming",
        source_revision="", checksum="",
        status="DISCOVERED", domain="subtitle",
        notes="Proven reachable: translation-ai-v0.1/src/tai/acquire.py streams "
            "en-zh/en-ja/en-ko/en-ms train. Subtitle domain — NOT equivalent to "
            "novel data. Smoke-ingest candidate #1.",
    ))

    c.append(_e(
        "hsc-wuxia-100k", name="HSC Wuxia 100k (zh-en)",
        source_type="parallel_corpus",
        languages=["zh", "en"], directions=["zh→en"],
        url="https://huggingface.co/datasets/HSilvosa/hsc-wuxia-100k",
        repo_id="HSilvosa/hsc-wuxia-100k",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — read dataset card live before any use.",
        publisher="HSilvosa (community)",
        citation="",
        estimated_size="UNVERIFIED — ~100k implied by name only; confirm live.",
        format="UNVERIFIED — confirm live (likely JSONL/parquet via Hub).",
        access_method="huggingface: Hub API + optional streaming sample",
        source_revision="", checksum="",
        status="DISCOVERED", domain="web_novel",
        notes="High literary priority IF verified (wuxia web-novel zh→en). "
            "Noise/contamination risks UNVERIFIED until sampled.",
    ))

    c.append(_e(
        "tomato-zh2en", name="TomatoMTL zh2en",
        source_type="parallel_corpus",
        languages=["zh", "en"], directions=["zh→en"],
        url="https://huggingface.co/datasets/TomatoMTL/tomato-zh2en",
        repo_id="TomatoMTL/tomato-zh2en",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — read dataset card live before any use.",
        publisher="TomatoMTL (community)",
        citation="",
        estimated_size="UNVERIFIED — confirm live via Hub API.",
        format="UNVERIFIED — confirm live.",
        access_method="huggingface: Hub API + optional streaming sample",
        source_revision="", checksum="",
        status="DISCOVERED", domain="web_novel",
        notes="Literary priority IF verified (reported novel zh→en). Confirm "
            "parallelism, size, and MT-vs-human provenance live.",
    ))

    c.append(_e(
        "qidian-webnovel", name="Qidian Webnovel Corpus (unverified concept)",
        source_type="literary_corpus",
        languages=["zh", "en"], directions=["zh→en"],
        url="https://www.qidian.com/",
        repo_id="",
        license="all-rights-reserved (assumed for Qidian source text)",
        license_evidence="No verified open parallel release identified. Qidian "
            "/ China Literature source text is proprietary. No scraping or "
            "ingestion without explicit rights.",
        publisher="China Literature / Qidian",
        citation="",
        estimated_size="UNVERIFIED — no open corpus identified.",
        format="UNVERIFIED",
        access_method="none verified — web text is proprietary",
        source_revision="", checksum="",
        status="DISCOVERED", domain="web_novel",
        notes="Concept only. Do NOT scrape. Keep as BLOCKED-candidate pending "
            "rights; track for licensed-partnership route only.",
    ))

    c.append(_e(
        "noveldataset", name="NabeelShar noveldataset",
        source_type="literary_corpus",
        languages=["zh", "en"], directions=["zh→en"],
        url="https://huggingface.co/datasets/NabeelShar/noveldataset",
        repo_id="NabeelShar/noveldataset",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — read dataset card live before any use.",
        publisher="NabeelShar (community)",
        citation="",
        estimated_size="UNVERIFIED — confirm live via Hub API.",
        format="UNVERIFIED — confirm live.",
        access_method="huggingface: Hub API + optional streaming sample",
        source_revision="", checksum="",
        status="DISCOVERED", domain="novel",
        notes="Literary priority IF verified. Confirm language coverage, "
            "parallelism, and provenance live.",
    ))

    c.append(_e(
        "diting", name="DITING (identifier ambiguous)",
        source_type="other",
        languages=["zh", "en"], directions=["zh→en"],
        url="",
        repo_id="",
        license="UNKNOWN",
        license_evidence="Identifier ambiguous — multiple unrelated uses of "
            "'DITING' (location/tech terms). No canonical dataset URL verified.",
        publisher="",
        citation="",
        estimated_size="UNVERIFIED",
        format="UNVERIFIED",
        access_method="UNVERIFIED — disambiguate first",
        source_revision="", checksum="",
        status="DISCOVERED", domain="other",
        notes="Parked pending disambiguation. Do not ingest until a canonical "
            "identifier + license is confirmed.",
    ))

    c.append(_e(
        "jparacrawl", name="JParaCrawl (en-ja web parallel)",
        source_type="parallel_corpus",
        languages=["ja", "en"], directions=["ja→en"],
        url="https://jparacrawl.org/",
        repo_id="",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — confirm current usage terms on site "
            "before any use (historically research-oriented).",
        publisher="NTT / Briggs (JParaCrawl project)",
        citation="Morishita et al. JParaCrawl. Details UNVERIFIED.",
        estimated_size="UNVERIFIED — v3 reported ~20M+ pairs in literature; "
            "confirm live from site/docs.",
        format="UNVERIFIED — confirm live (historically TSV/text downloads).",
        access_method="http download (confirm live URL + checksum)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="general",
        notes="Largest ja-en candidate class. Web/general domain — useful for "
            "ja→en volume, NOT a substitute for literary data. JA gap filler.",
    ))

    c.append(_e(
        "jesc", name="JESC Japanese-English Subtitle Corpus",
        source_type="parallel_corpus",
        languages=["ja", "en"], directions=["ja→en"],
        url="https://nlp.stanford.edu/projects/jesc/",
        repo_id="",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — confirm usage terms on project page "
            "before any use.",
        publisher="Stanford NLP (Clement & Freitag)",
        citation="Clement & Freitag JESC. Details UNVERIFIED.",
        estimated_size="UNVERIFIED — ~3.2M pairs reported in literature; "
            "confirm live.",
        format="UNVERIFIED — confirm live (historically TSV).",
        access_method="http download (confirm live URL + checksum)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="subtitle",
        notes="Dialogue/subtitle domain — do NOT treat as novel-equivalent. "
            "JA gap filler for volume + dialogue coverage.",
    ))

    c.append(_e(
        "openmantra", name="OpenMantra (identifier ambiguous)",
        source_type="other",
        languages=["zh", "en"], directions=["zh→en"],
        url="",
        repo_id="",
        license="UNKNOWN",
        license_evidence="No canonical translation-parallel 'OpenMantra' "
            "dataset verified. Name collides with unrelated projects.",
        publisher="",
        citation="",
        estimated_size="UNVERIFIED",
        format="UNVERIFIED",
        access_method="UNVERIFIED — disambiguate first",
        source_revision="", checksum="",
        status="DISCOVERED", domain="other",
        notes="Parked pending disambiguation. Do not ingest until canonical "
            "identifier + license confirmed.",
    ))

    c.append(_e(
        "aozora-ja-lit", name="Aozora Bunko (ja monolingual literary)",
        source_type="literary_corpus",
        languages=["ja"], directions=[],
        url="https://www.aozora.gr.jp/",
        repo_id="",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — Aozora hosts public-domain ja texts but "
            "per-work rights vary; confirm per-text status before any use. No "
            "parallel EN verified.",
        publisher="Aozora Bunko",
        citation="",
        estimated_size="UNVERIFIED — thousands of works; confirm live.",
        format="UNVERIFIED — confirm live (historically text/HTML).",
        access_method="http (confirm live)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="literary",
        notes="Monolingual ja literary. NOT parallel — useful only if a "
            "verified parallel derivative or alignment project is found.",
    ))

    c.append(_e(
        "opus-qed-koen", name="OPUS QED Korean-English",
        source_type="parallel_corpus",
        languages=["ko", "en"], directions=["ko→en"],
        url="https://opus.nlpl.eu/QED/en&ko/v2a/QED",
        repo_id="",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — OPUS aggregates upstream subtitles; "
            "per-sentence rights UNVERIFIED.",
        publisher="OPUS / QED",
        citation="",
        estimated_size="UNVERIFIED — confirm live from OPUS counts.",
        format="UNVERIFIED — confirm live (OPUS TMX/txt).",
        access_method="http download via OPUS (confirm live URL)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="subtitle",
        notes="KO gap filler candidate. Subtitle domain. Confirm size/license "
            "live before ingestion.",
    ))

    c.append(_e(
        "aihub-koen", name="AI-Hub Korean-English parallel (access-gated)",
        source_type="parallel_corpus",
        languages=["ko", "en"], directions=["ko→en"],
        url="https://aihub.or.kr/",
        repo_id="",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — AI-Hub datasets typically require "
            "application + agreement; confirm live.",
        publisher="AI-Hub (Korea)",
        citation="",
        estimated_size="UNVERIFIED",
        format="UNVERIFIED",
        access_method="gated application (expect BLOCKED_ACCESS without grant)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="general",
        notes="KO volume lives behind access gates. Track; expect "
            "BLOCKED_ACCESS unless an approved grant exists. Never bypass.",
    ))

    c.append(_e(
        "flores-plus", name="FLORES+ (eval benchmark)",
        source_type="eval_benchmark",
        languages=["zh", "ja", "ko", "ms", "en"],
        directions=["zh→en", "ja→en", "ko→en", "ms→en"],
        url="https://huggingface.co/datasets/facebook/flores",
        repo_id="facebook/flores",
        license="CC-BY-SA-4.0 (to be verified from repo card)",
        license_evidence="Card states CC-BY-SA-4.0 per public record — VERIFY "
            "live. Share-alike obligation applies regardless.",
        publisher="Meta AI",
        citation="Goyal et al. FLORES-200. DOI UNVERIFIED.",
        estimated_size="UNVERIFIED — ~1-3k sentences per language dev/devtest; "
            "confirm live. Eval-scale by design.",
        format="Hugging Face datasets",
        access_method="huggingface: Hub API",
        source_revision="", checksum="",
        status="DISCOVERED", domain="general",
        notes="EVAL ONLY — must NEVER enter training splits (contamination). "
            "Covers all four directions incl. JA/KO/MS gaps for measurement.",
    ))

    c.append(_e(
        "tatoeba-msen", name="Tatoeba Malay-English",
        source_type="parallel_corpus",
        languages=["ms", "en"], directions=["ms→en"],
        url="https://tatoeba.org/",
        repo_id="",
        license="CC-BY-2.0-FR (to be verified from Tatoeba terms)",
        license_evidence="Tatoeba sentences historically CC-BY-2.0-FR — VERIFY "
            "live before any use.",
        publisher="Tatoeba community",
        citation="",
        estimated_size="UNVERIFIED — small (tens of thousands at most); "
            "confirm live downloads.",
        format="UNVERIFIED — confirm live (historically TSV).",
        access_method="http download via downloads.tatoeba.org (confirm live)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="general",
        notes="MS gap filler. Small, general-domain, sentence-level — useful "
            "for MS volume baseline, not literary.",
    ))

    c.append(_e(
        "cc-cedict", name="CC-CEDICT (zh-en dictionary)",
        source_type="dictionary",
        languages=["zh", "en"], directions=["zh→en"],
        url="https://github.com/mdbg/cc-cedict",
        repo_id="",
        license="CC-BY-SA-4.0 (to be verified from repo)",
        license_evidence="Repo historically CC-BY-SA — VERIFY live file header "
            "before any use. Share-alike applies.",
        publisher="MDBG / CC-CEDICT editors",
        citation="",
        estimated_size="UNVERIFIED — ~120k entries reported; confirm live.",
        format="UNVERIFIED — confirm live (historically UTF-8 text).",
        access_method="git/http (confirm live + checksum)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="dictionary",
        notes="Lexical resource — terminology grounding for zh→en, not "
            "sentence training data. Verify revision pin + checksum.",
    ))

    c.append(_e(
        "jmdict", name="JMdict/EDICT (ja-en dictionary)",
        source_type="dictionary",
        languages=["ja", "en"], directions=["ja→en"],
        url="https://www.edrdg.org/jmdict/j_jmdict.html",
        repo_id="",
        license="CC-BY-SA-4.0 (to be verified from EDRDG terms)",
        license_evidence="EDRDG historically CC-BY-SA — VERIFY live before "
            "any use. Share-alike + attribution apply.",
        publisher="EDRDG",
        citation="",
        estimated_size="UNVERIFIED — ~190k entries reported; confirm live.",
        format="UNVERIFIED — confirm live (historically XML).",
        access_method="http download (confirm live URL + checksum)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="dictionary",
        notes="Lexical resource for ja→en grounding. JA gap helper. Verify "
            "revision + checksum; XML parse path needed.",
    ))

    c.append(_e(
        "koen-wikt", name="Korean-English Wiktionary extract (unverified)",
        source_type="dictionary",
        languages=["ko", "en"], directions=["ko→en"],
        url="https://dumps.wikimedia.org/",
        repo_id="",
        license="CC-BY-SA-4.0 (to be verified per dump)",
        license_evidence="Wiktionary dumps historically CC-BY-SA — VERIFY live "
            "per-dump terms before any use.",
        publisher="Wikimedia community",
        citation="",
        estimated_size="UNVERIFIED — confirm live.",
        format="UNVERIFIED — confirm live (XML/dump).",
        access_method="http dump download (confirm live + checksum)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="dictionary",
        notes="KO lexical gap helper. Extraction + parsing work required; "
            "verify dump date + checksum.",
    ))

    c.append(_e(
        "msmy-dict", name="Malay-English dictionary resource (unverified)",
        source_type="dictionary",
        languages=["ms", "en"], directions=["ms→en"],
        url="",
        repo_id="",
        license="UNKNOWN",
        license_evidence="No canonical open ms-en dictionary release verified. "
            "Candidates (DBP Kamus, community lists) have unclear terms.",
        publisher="",
        citation="",
        estimated_size="UNVERIFIED",
        format="UNVERIFIED",
        access_method="UNVERIFIED — identify a licensed open release first",
        source_revision="", checksum="",
        status="DISCOVERED", domain="dictionary",
        notes="MS lexical gap is OPEN. Do not ingest scraped dictionary text "
            "without explicit license. Track as gap.",
    ))

    c.append(_e(
        "wmt-eval", name="WMT news test sets (eval benchmark family)",
        source_type="eval_benchmark",
        languages=["zh", "ja", "ko", "en"], directions=["zh→en", "ja→en"],
        url="https://www.statmt.org/wmt23/",
        repo_id="",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — WMT sets carry per-year terms; confirm "
            "live before any use. KO coverage varies by year.",
        publisher="WMT organizers",
        citation="",
        estimated_size="UNVERIFIED — ~2k sentences per test set; confirm live.",
        format="UNVERIFIED — confirm live (historically SGML/text).",
        access_method="http download (confirm live URL + checksum)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="academic",
        notes="EVAL ONLY — never train (contamination). zh/ja covered; ko/ms "
            "coverage is the gap to confirm per-year.",
    ))

    c.append(_e(
        "paracrawl-zhen", name="ParaCrawl zh-en (web parallel)",
        source_type="parallel_corpus",
        languages=["zh", "en"], directions=["zh→en"],
        url="https://paracrawl.eu/",
        repo_id="",
        license="UNKNOWN",
        license_evidence="UNVERIFIED — ParaCrawl aggregates web crawls; "
            "per-sentence rights UNVERIFIED.",
        publisher="ParaCrawl project",
        citation="",
        estimated_size="UNVERIFIED — millions claimed; confirm live counts.",
        format="UNVERIFIED — confirm live (historically TMX/text).",
        access_method="http download (confirm live URL + checksum)",
        source_revision="", checksum="",
        status="DISCOVERED", domain="general",
        notes="zh→en volume candidate. Web/general domain with known noise — "
            "cheap filters + dedup required before any use.",
    ))

    return c
