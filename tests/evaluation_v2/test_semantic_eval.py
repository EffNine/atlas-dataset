"""Tests for evaluation_engine.v2.semantic_eval — rubric-based answer scoring,
keyword-stuffing detection, and reference agreement.

Adversarial cases required by Phase 5A.2:
  * correct answer with different wording (paraphrase) must score well,
  * wrong answer that re-uses question keywords must score lower than a good
    answer (keyword stuffing),
  * partial correctness must get partial credit.
"""

from __future__ import annotations

import pytest

from evaluation_engine.v2.semantic_eval import (
    LLMJudge,
    RubricJudge,
    SemanticAnswerEvaluator,
    compare,
    score_coverage,
    score_novelty,
)


@pytest.fixture(scope="module")
def question():
    return "Explain how RAG embeddings work for retrieval."


@pytest.fixture(scope="module")
def reference():
    return ("RAG embeddings are dense vector representations of queries and "
            "documents produced by an encoder model; retrieval relevance is "
            "determined by vector similarity.")


@pytest.fixture(scope="module")
def good_answer():
    return ("RAG embeddings encode queries and documents as dense vectors "
            "using an encoder model. The retriever ranks passages by vector "
            "similarity to the query, then feeds the top results to the "
            "generator.")


@pytest.fixture(scope="module")
def keyword_stuffed():
    return ("RAG embeddings. Embeddings. RAG retrieval. RAG embeddings work "
            "for retrieval because embeddings and retrieval and RAG "
            "embeddings and retrieval.")


class TestRubricCriteria:
    def test_novelty_punishes_reuse(self):
        q = "RAG embeddings retrieval"
        stuffed = "rag embeddings retrieval rag retrieval embeddings"
        normal = "dense vector representations of queries and documents"
        assert score_novelty(q, stuffed)[0] < score_novelty(q, normal)[0]

    def test_coverage_empty_answer(self):
        assert score_coverage("How does X work?", "")[0] == 0.0


class TestSemanticEvaluation:
    def test_good_answer_scores_higher_than_keyword_stuff(self, question,
                                                          reference,
                                                          good_answer,
                                                          keyword_stuffed):
        good = compare(question=question, reference=reference, answer=good_answer)
        bad = compare(question=question, reference=reference, answer=keyword_stuffed)
        assert good["score"] > bad["score"]

    def test_correct_answer_different_wording(self, question, reference,
                                              good_answer):
        """A paraphrase with different vocabulary still scores well."""
        r = compare(question=question, reference=reference, answer=good_answer)
        assert r["score"] >= 0.5

    def test_keyword_stuffing_flagged(self, question, reference, keyword_stuffed):
        r = compare(question=question, reference=reference, answer=keyword_stuffed)
        assert r["rubric"]["novelty"] < 0.8

    def test_partial_correctness(self, question, reference):
        """Answer covering only one of two demanded parts gets partial credit
        vs the fuller reference."""
        partial = "RAG embeddings are dense vectors produced by an encoder model."
        full = ("RAG embeddings are dense vectors from an encoder model; "
                "retrieval ranks passages by cosine similarity to the query "
                "vector, returning the top-k to the generator.")
        a = compare(question=question, reference=reference, answer=partial)
        b = compare(question=question, reference=reference, answer=full)
        assert 0.0 < a["score"] <= b["score"]

    def test_empty_answer(self, question, reference):
        r = compare(question=question, reference=reference, answer="")
        assert r["score"] == 0.0

    def test_vague_answer_penalized(self, question, reference):
        vague = ("I think RAG embeddings probably help somehow, maybe with "
                 "retrieval and stuff, not sure though.")
        good = ("RAG embeddings encode queries and documents as dense vectors "
                "using an encoder model. The retriever ranks passages by "
                "vector similarity to the query, then feeds the top results "
                "to the generator.")
        assert (compare(question=question, reference=reference, answer=vague)["score"]
                < compare(question=question, reference=reference, answer=good)["score"])


class TestRubricExplainability:
    def test_explainable_reasons(self, question, reference, good_answer):
        r = compare(question=question, reference=reference, answer=good_answer)
        for criterion, reason in r["criteria"].items():
            assert isinstance(reason["reason"], str) and reason["reason"]
            assert 0.0 <= reason["score"] <= 1.0
        for criterion, score in r["rubric"].items():
            assert 0.0 <= score <= 1.0

    def test_rubric_judge_weighted(self):
        j = RubricJudge()
        out = j.judge("What is X?", "X is a thing.", "X is a thing and more.")
        assert 0.0 <= out["score"] <= 1.0
        assert set(out["criteria"]) == {"coverage", "specificity", "novelty",
                                        "grounding", "structure", "clarity"}

    def test_llm_judge_not_available_offline(self):
        """LLMJudge is a pluggable interface for a CUDA-bound runtime; it must
        not silently fall back when no model is configured."""
        j = LLMJudge()
        with pytest.raises(NotImplementedError):
            j.judge("q", "ref", "answer")


class TestSemanticEngineAPI:
    def test_evaluate_record_shape(self, question, reference, good_answer):
        ev = SemanticAnswerEvaluator().evaluate(question=question,
                                                reference=reference,
                                                answer=good_answer)
        assert 0.0 <= ev.score <= 1.0
        assert ev.method == "rubric"
        assert ev.reason
        assert ev.confidence > 0.0
