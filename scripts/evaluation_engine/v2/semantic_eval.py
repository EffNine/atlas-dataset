"""semantic_eval.py — QEE v2 rubric-based semantic answer evaluation.

Problem addressed
-----------------
QEE v1 scored free-text answers with keyword hits and length heuristics:
* any answer containing domain words scored near-maximum ("technical
  correctness" and "relevance" rewarded keyword presence),
* a wrong answer that reuses question keywords could score as high as a
  correct one (no anti-stuffing signal),
* "clarity: short = clear" rewarded brevity that humans judged incomplete.

Design
------
The v2 semantic evaluator scores answers against a **rubric** of dimensions,
each with a deterministic, explainable score:

  * ``coverage``     — does the answer address the question's demand?
  * ``specificity``  — concrete, grounded detail vs. vague hedging.
  * ``novelty``      — new informational content vs. keyword echo
                      (anti-stuffing).
  * ``grounding``    — citations / sources / URLs when the domain needs it.
  * ``structure``    — organization appropriate to the question.
  * ``clarity``      — readable, well-formed prose.

Each criterion returns ``(score 0..1, reason)`` so results stay auditable.
A pluggable ``JudgeBackend`` allows a semantic judge (currently the
deterministic rubric; a CUDA-bound LLM judge interface is provided but never
executed here — Atlas evaluation is read-only and network-isolated).

The rubric deliberately does **not** reward keyword presence by itself; the
``novelty`` term subtracts credit when the answer merely restates question
terms without adding content.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .normalize import content_tokens, split_sentences, token_set_similarity

_URL_RE = re.compile(r"https?://|www\.")
_HEDGE_RE = re.compile(
    r"\b(?:maybe|possibly|perhaps|i think|might be|some stuff|sort of|"
    r"kind of|not sure|roughly correct|probably)\b", re.I
)
_ALLCAPS_RE = re.compile(r"\b[A-Z]{4,}\b")
_ENUM_RE = re.compile(r"(?m)(^\s*[-*]\s+|^\s*\d+\.\s+|^#+\s)")
_DIGIT_RE = re.compile(r"\d")
_CODE_FENCE_RE = re.compile(r"```")

RUBRIC_WEIGHTS = {
    "coverage": 0.36,
    "specificity": 0.16,
    "novelty": 0.20,
    "structure": 0.10,
    "grounding": 0.08,
    "clarity": 0.10,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _avg_sentence_words(text: str) -> float:
    sents = split_sentences(text)
    if not sents:
        return 0.0
    return sum(len(s.split()) for s in sents) / len(sents)


def score_coverage(question: str, answer: str) -> tuple[float, str]:
    """Does the answer address the question's demand and provide substance?

    ``substance`` counts informative content tokens (bounded), which is the
    completeness signal humans reward without rewarding keyword re-use
    (novelty is tracked separately). Soft penalties apply for off-topic and
    very short answers instead of hard caps so scores stay continuous.
    """
    q_tokens = content_tokens(question)
    a_tokens = content_tokens(answer)
    if not q_tokens:
        return 0.5, "question has no extractable content tokens"
    if not a_tokens:
        return 0.0, "answer has no content tokens"

    covered = sum(1 for t in q_tokens if t in a_tokens)
    cover_ratio = covered / len(q_tokens)

    # Substance dominates: the completeness signal humans reward is how much
    # real information the answer carries. Cover-ratio still guards against
    # off-topic filler. (Novelty tracks verbatim keyword re-use separately.)
    substance = _clamp(len(a_tokens) / 14.0)
    coverage = 0.2 * cover_ratio + 0.8 * substance
    if cover_ratio == 0:
        coverage -= 0.10       # addresses none of the question's terms
    if len(answer.split()) < 8:
        coverage -= 0.10       # brevity penalty (humans penalize this)
    return round(_clamp(coverage), 3), (
        f"covers {covered}/{len(q_tokens)} question terms; "
        f"informative tokens {len(a_tokens)} (substance {substance:.2f})")


def score_specificity(question: str, answer: str) -> tuple[float, str]:
    """Concrete detail and precision vs. vague hedging."""
    hedge_hits = len(_HEDGE_RE.findall(answer.lower()))
    has_numbers = bool(_DIGIT_RE.search(answer))
    specific_terms = len(
        set(content_tokens(answer)) - set(content_tokens(question))
    )
    base = 0.30 + (0.15 if has_numbers else 0.0) + 0.06 * min(specific_terms, 4)
    if hedge_hits:
        base -= 0.15 * min(hedge_hits, 3)
    reason = (
        f"hedges={hedge_hits}, specific_terms={specific_terms}, "
        f"has_numbers={has_numbers}")
    return round(_clamp(base), 3), reason


def score_novelty(question: str, answer: str) -> tuple[float, str]:
    """Anti-keyword-stuffing: new content vs. re-use of question words."""
    q_tokens = set(content_tokens(question))
    a_tokens = content_tokens(answer)
    if not a_tokens:
        return 0.0, "no answer content"
    reuse = sum(1 for t in a_tokens if t in q_tokens)
    reuse_ratio = reuse / len(a_tokens)
    # Heavy verbatim re-use of question terms with nothing new = stuffed.
    novel_ratio = 1.0 - reuse_ratio
    score = _clamp(0.3 + 0.9 * novel_ratio)
    reason = f"reuse_ratio={reuse_ratio:.2f}, novel_ratio={novel_ratio:.2f}"
    return round(score, 3), reason


def score_grounding(question: str, answer: str) -> tuple[float, str]:
    """Citations / sources / URLs, expected only for factual-knowledge answers.

    Conceptual questions ("explain how ... works", "why", "what is") do not
    require external citations; requiring them there would penalize good
    explanations, so grounding is scored neutrally when not expected.
    """
    expected = bool(re.search(
        r"(?i)(cite|source|reference|provenance|according to|per the (docs|paper)|"
        r"where does|who wrote|when was|facts? about)", question))
    urls = len(_URL_RE.findall(answer))
    source_mentions = len(re.findall(
        r"(?i)(source|according to|references?|cites?|per )", answer))
    evidence = urls + source_mentions
    if expected:
        if evidence:
            return round(_clamp(0.4 + 0.1 * min(evidence, 6)), 3), (
                f"{evidence} source/url signal(s) present")
        return 0.1, "factual question; no citation or source evidence"
    if evidence:
        return round(_clamp(0.5 + 0.1 * min(evidence, 4)), 3), (
            f"{evidence} source/url signal(s) present")
    return 0.5, "grounding not required for conceptual question"


def score_structure(question: str, answer: str) -> tuple[float, str]:
    """Organization appropriate to the question type."""
    wants_list = any(w in question.lower() for w in
                     ("list", "steps", "step", "how to", "outline", "compare"))
    has_enum = bool(_ENUM_RE.search(answer))
    has_fence = bool(_CODE_FENCE_RE.search(answer))
    has_headers = bool(re.search(r"(?m)^#{1,4}\s", answer))
    structured = has_enum or has_fence or has_headers
    if (wants_list and structured) or (not wants_list and len(split_sentences(answer)) >= 2):
        return 0.8, "appropriate structure for question"
    if wants_list and not structured:
        return 0.4, "question asks for a list/steps but answer is unstructured"
    return 0.6, "single-paragraph prose (acceptable for the question)"


def score_clarity(answer: str) -> tuple[float, str]:
    """Readable, well-formed prose."""
    sents = split_sentences(answer)
    if not sents:
        return 0.2, "no sentences"
    avg = _avg_sentence_words(answer)
    if 8 <= avg <= 25:
        base = 0.92
    elif 4 <= avg < 8 or 25 < avg <= 40:
        base = 0.7
    else:
        base = 0.45
    caps = len(_ALLCAPS_RE.findall(answer))
    if caps > 3:
        base -= 0.15
    return round(_clamp(base), 3), f"avg sentence {avg:.0f} words, ALLCAPS spikes={caps}"


def score_reference_agreement(question: str, reference: str,
                             answer: str) -> tuple[float, str]:
    """Content overlap between answer and reference (when one exists)."""
    if not reference or not reference.strip():
        return 0.5, "no reference available"
    sim = token_set_similarity(content_tokens(reference), content_tokens(answer))
    return round(sim, 3), f"reference content similarity {sim:.2f}"


@dataclass
class SemanticResult:
    score: float
    rubric: dict
    correct: bool | None
    confidence: float
    reason: str
    method: str = "rubric"
    details: dict = field(default_factory=dict)
    criteria: dict = field(default_factory=dict)


class JudgeBackend(ABC):
    """Pluggable semantic judge backend."""

    name = "abstract"

    @abstractmethod
    def judge(self, question: str, reference: str, answer: str) -> dict:
        """Return {"score": 0..1, "reason": str, "details": {...}}."""


class RubricJudge(JudgeBackend):
    """Deterministic, explainable rubric judge (default backend)."""

    name = "rubric"

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = dict(RUBRIC_WEIGHTS)
        if weights:
            self.weights.update(weights)

    def judge(self, question: str, reference: str, answer: str) -> dict:
        criteria = {}
        criteria["coverage"] = score_coverage(question, answer)
        criteria["specificity"] = score_specificity(question, answer)
        criteria["novelty"] = score_novelty(question, answer)
        criteria["grounding"] = score_grounding(question, answer)
        criteria["structure"] = score_structure(question, answer)
        criteria["clarity"] = score_clarity(answer)
        ref_agreement = score_reference_agreement(question, reference, answer)

        weighted = sum(self.weights[k] * v for k, (v, _) in criteria.items())
        score = round(_clamp(weighted), 4)
        return {
            "score": score,
            "criteria": {
                k: {"score": round(v, 3), "reason": r}
                for k, (v, r) in criteria.items()
            },
            "details": {
                "weights": self.weights,
                "reference_agreement": ref_agreement[0],
                "reference_agreement_reason": ref_agreement[1],
            },
        }


class LLMJudge(JudgeBackend):
    """Semantic judge backed by an LLM (CUDA-bound).

    Not executed inside Atlas evaluation: evaluation is read-only and
    network-isolated, and no model runtime is required for the deterministic
    pipeline. Instantiate on the training host to upgrade the rubric verdict
    with a model-based semantic check while keeping per-criterion reasons.
    """

    name = "llm"

    def __init__(self, backend: str = "local", model_id: str = "") -> None:
        self.backend = backend
        self.model_id = model_id

    def judge(self, question: str, reference: str, answer: str) -> dict:
        raise NotImplementedError(
            "LLMJudge is a pluggable interface for a CUDA-bound runtime. "
            "Atlas evaluation runs read-only without a model; configure a "
            "concrete backend on the training host and validate it against "
            "human review before enabling unsupervised use."
        )


class SemanticAnswerEvaluator:
    """Evaluate a free-text answer with an explainable rubric."""

    def __init__(self, judge: JudgeBackend | None = None) -> None:
        self.judge = judge if judge is not None else RubricJudge()

    def evaluate(self, question: str = "", reference: str = "",
                 answer: str = "") -> SemanticResult:
        if not answer or not answer.strip():
            return SemanticResult(
                score=0.0, rubric={}, correct=False, confidence=0.2,
                reason="empty answer",
            )
        result = self.judge.judge(question, reference, answer)
        # Reference agreement is a mild modifier only: token overlap is a crude
        # paraphrase detector, so it must not dominate or punish good rewording.
        ref_agree = result["details"].get("reference_agreement", 0.5)
        blended = _clamp(0.9 * result["score"] + 0.1 * ref_agree)
        correct = (
            True if blended >= 0.8 and result["score"] >= 0.7 else
            None if result["score"] < 0.4 else False
        )
        return SemanticResult(
            score=round(blended, 4),
            rubric={k: v["score"] for k, v in result["criteria"].items()},
            correct=correct,
            confidence=0.7,
            reason=(f"rubric score {result['score']:.2f}; "
                    f"reference agreement {ref_agree:.2f}"),
            details=result["details"],
            criteria=result["criteria"],
        )


def compare(question: str = "", reference: str = "", answer: str = "") -> dict:
    """Convenience wrapper used by tests/CLI."""
    r = SemanticAnswerEvaluator().evaluate(question, reference, answer)
    return {
        "score": r.score,
        "correct": r.correct,
        "rubric": r.rubric,          # {criterion: score 0..1}
        "criteria": r.criteria,      # {criterion: {score, reason}}
        "confidence": r.confidence,
        "reason": r.reason,
    }
