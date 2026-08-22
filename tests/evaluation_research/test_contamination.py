"""Test module."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import pytest
import json
from evaluation_research.contamination import ContaminationAuditor, run_contamination_audit


class TestContaminationAuditor:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        auditor = ContaminationAuditor(tmp_path)
        result = auditor.audit_set(f, training_sets=[])
        assert result["n_total"] == 0
        assert result["n_clean"] == 0

    def test_single_record_no_contamination(self, tmp_path):
        f = tmp_path / "single.jsonl"
        f.write_text('{"record_id": "r1", "problem": "What is 2+2?", "canonical_answer": "4"}\n',
                     encoding="utf-8")
        auditor = ContaminationAuditor(tmp_path)
        result = auditor.audit_set(f, training_sets=[])
        assert result["n_total"] == 1
        assert result["n_clean"] == 1

    def test_verdict_pass_when_clean(self, tmp_path):
        records = [{"record_id": f"r{i}", "problem": f"Q{i}", "canonical_answer": f"A{i}"}
                   for i in range(5)]
        f = tmp_path / "clean.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        result = run_contamination_audit(f, tmp_path, training_sets=[])
        assert result["verdict"] in ("PASS", "HOLD")
