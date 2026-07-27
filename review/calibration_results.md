# Phase 3C Calibration Results Summary

**Date:** 2026-07-27  
**Reviews:** 100  
**Matched candidates:** 100  
**Missing candidates:** 0  

## Key Metrics
- **MAE:** 0.18
- **Within-1 agreement:** 100%
- **Threshold F1:** 0.913
- **Mean bias (auto - human):** +0.14

## Readiness Verdict
**READY_FOR_CALIBRATED_AUTO_REVIEW**

Auto-score agrees with human review within tolerance. Bulk ingestion may proceed with stratum-level corrections and spot-check review.

## Artifacts
- Full report: `docs/human_calibration_report.md`
- Machine-readable report: `metadata/calibration_report.json`
- Human reviews: `review/quality_reviews.jsonl`

## Notes
- All 100 pilot Knowledge Objects were reviewed.
- No synthetic review data was included in calibration.
- Dataset size in `raw/` and `curated/` remains unchanged.
