#!/usr/bin/env python3
"""
prompt_builder.py — Judge prompt construction for the EffNine Benchmark (EB).

Builds structured prompts for cloud judge evaluations. Prompts include:
  - Task description and context
  - Model response to evaluate
  - Evaluation rubric and criteria
  - Scoring instructions and constraints

The prompt explicitly instructs the judge to evaluate, not solve.
"""

from __future__ import annotations

from typing import Any

from ..core.schema import Task, TaskResult
from ..core.types import Capability


class JudgePromptBuilder:
    """
    Constructs judge evaluation prompts.

    Prompts are structured JSON-compatible message lists that instruct
    the judge model to evaluate a submitted answer against provided
    criteria.
    """

    SYSTEM_PROMPT = (
        "You are an expert benchmark evaluator. Your role is to assess model responses "
        "against well-defined criteria — NOT to solve the task yourself.\n\n"
        "Evaluation principles:\n"
        "- Evaluate the submitted answer objectively against the provided criteria.\n"
        "- Do not reward verbosity; reward precision and correctness.\n"
        "- Distinguish fact from assumption; penalize unsupported confident claims.\n"
        "- Use only the evidence and context provided; do not bring in external solutions.\n"
        "- If the answer is incomplete, score based on what is present.\n"
        "- Return your evaluation as structured JSON."
    )

    def build(
        self,
        task: Task,
        result: TaskResult,
        criteria: list[dict[str, Any]],
        max_score: float = 1.0,
    ) -> list[dict[str, str]]:
        """
        Build a message list for judge evaluation.

        Args:
            task: The benchmark task.
            result: The TaskResult containing the model's response.
            criteria: Evaluation criteria with id, weight, description.
            max_score: Maximum possible score.

        Returns:
            List of message dicts suitable for OpenAI chat completions.
        """
        model_response = result.raw_response or ""

        user_content = self._build_user_prompt(task, model_response, criteria, max_score)

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _build_user_prompt(
        self,
        task: Task,
        model_response: str,
        criteria: list[dict[str, Any]],
        max_score: float,
    ) -> str:
        """Build the user-facing prompt content."""
        lines: list[str] = []

        # Task context
        lines.append("## EVALUATION TASK")
        lines.append(f"Task ID: {task.id}")
        lines.append(f"Category: {task.category}")
        lines.append(f"Capabilities: {', '.join(c.value for c in task.capabilities)}")
        lines.append("")

        # Task prompt
        lines.append("## ORIGINAL TASK")
        lines.append(task.prompt)
        if task.context:
            ctx_lines = []
            for k, v in task.context.items():
                if k in ("expected", "answer", "acceptable_answers"):
                    continue  # Don't leak ground truth
                ctx_lines.append(f"- {k}: {v}")
            if ctx_lines:
                lines.append("## CONTEXT")
                lines.append("\n".join(ctx_lines))
                lines.append("")

        # Model response
        lines.append("## MODEL RESPONSE")
        lines.append(model_response[:8000])  # Cap response length
        lines.append("")

        # Criteria
        lines.append("## EVALUATION CRITERIA")
        lines.append(f"Maximum score: {max_score}")
        lines.append("")
        for i, crit in enumerate(criteria, 1):
            crit_id = crit.get("id", f"criteria_{i}")
            crit_desc = crit.get("description", crit.get("name", crit_id))
            crit_weight = crit.get("weight", 1.0)
            lines.append(f"{i}. **{crit_id}** (weight: {crit_weight})")
            lines.append(f"   {crit_desc}")
            if "rubric" in crit:
                lines.append(f"   Rubric: {crit['rubric']}")
            lines.append("")

        # Output format instruction
        format_instr = (
            "Return a JSON object with these fields:\n"
            "- `score`: float between 0 and {max_score}\n"
            "- `criterion_scores`: object mapping criterion IDs to float scores\n"
            "- `reasoning_summary`: brief explanation of your assessment\n"
            "- `evidence`: array of specific evidence points from the response\n"
            "- `flags`: array of any issues (e.g. 'incomplete', 'off-topic')\n"
            "- `confidence`: float between 0 and 1 indicating your certainty"
        )
        lines.append("## OUTPUT FORMAT")
        lines.append(format_instr.format(max_score=max_score))

        return "\n".join(lines)

    def build_failure_prompt(self, error: str, max_retries: int = 2) -> str:
        """Build a prompt for when the judge output was malformed."""
        return (
            f"Your previous response was malformed. Error: {error}\n"
            f"Please return a valid JSON object with score, criterion_scores, "
            f"reasoning_summary, evidence, flags, and confidence fields.\n"
            f"Retry attempt {max_retries + 1}. Return ONLY valid JSON."
        )

    def build_long_evidence_prompt(
        self,
        task: Task,
        result: TaskResult,
        stage_results: list[Any],
        stages: list[Any],
        criteria: list[dict[str, Any]],
        max_score: float = 1.0,
        max_evidence_chars: int = 12000,
    ) -> list[dict[str, str]]:
        """
        Build a judge prompt with LONG-specific stage evidence.

        Evidence is bounded to max_evidence_chars to prevent prompt overflow.
        Secrets and ground truth are excluded.
        """
        lines: list[str] = []

        # Task context
        lines.append("## EVALUATION TASK")
        lines.append(f"Task ID: {task.id}")
        lines.append(f"Category: {task.category}")
        lines.append(f"Mode: LONG (multi-stage engineering workflow)")
        lines.append(f"Capabilities: {', '.join(c.value for c in task.capabilities)}")
        lines.append("")

        # Task prompt
        lines.append("## ORIGINAL TASK")
        lines.append(task.prompt)
        lines.append("")

        # Stage definitions and results (bounded)
        lines.append("## STAGE EXECUTION RESULTS")
        evidence_chunks: list[str] = []

        for sr in stage_results:
            stage_id = getattr(sr, "stage_id", "unknown")
            stage_name = getattr(sr, "stage_name", "")
            stage_status = getattr(sr, "status", "unknown")
            stage_score = getattr(sr, "score", None)
            stage_output = getattr(sr, "output", "") or ""
            stage_error = getattr(sr, "error", None)

            chunk = f"Stage {stage_id} ({stage_name}): status={stage_status}"
            if stage_score is not None:
                chunk += f", score={stage_score:.3f}"
            if stage_error:
                chunk += f", error={stage_error}"
            chunk += f"\n  Output: {stage_output[:1500]}"

            evidence_chunks.append(chunk)

        # Requirement changes
        req_changes = []
        for sd in stages:
            rc = getattr(sd, "requirement_change", None) or (
                sd.get("requirement_change") if isinstance(sd, dict) else None
            )
            if rc:
                req_changes.append(str(rc))
        if req_changes:
            evidence_chunks.append(f"Requirement changes: {req_changes}")

        # Delivery criteria
        delivery = task.context.get("delivery_criteria")
        if delivery:
            evidence_chunks.append(f"Delivery criteria: {delivery}")

        # Final response
        final_response = result.raw_response or ""
        evidence_chunks.append(f"Final delivery: {final_response[:2000]}")

        # Bounded concatenation
        combined = "\n\n".join(evidence_chunks)
        if len(combined) > max_evidence_chars:
            combined = combined[:max_evidence_chars] + "\n... [truncated]"

        lines.append(combined)
        lines.append("")

        # Criteria
        lines.append("## EVALUATION CRITERIA")
        lines.append(f"Maximum score: {max_score}")
        lines.append("")
        for i, crit in enumerate(criteria, 1):
            crit_id = crit.get("id", f"criteria_{i}")
            crit_desc = crit.get("description", crit.get("name", crit_id))
            crit_weight = crit.get("weight", 1.0)
            lines.append(f"{i}. **{crit_id}** (weight: {crit_weight})")
            lines.append(f"   {crit_desc}")
            lines.append("")

        # Output format instruction
        format_instr = (
            "Return a JSON object with these fields:\n"
            "- `score`: float between 0 and {max_score}\n"
            "- `criterion_scores`: object mapping criterion IDs to float scores\n"
            "- `reasoning_summary`: brief explanation of your assessment\n"
            "- `evidence`: array of specific evidence points from the stage results\n"
            "- `flags`: array of any issues (e.g. 'incomplete', 'regression', 'overfit')\n"
            "- `confidence`: float between 0 and 1 indicating your certainty"
        )
        lines.append("## OUTPUT FORMAT")
        lines.append(format_instr.format(max_score=max_score))

        user_content = "\n".join(lines)

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
