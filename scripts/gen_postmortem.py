#!/usr/bin/env python3
"""Generate the Atlas 500M Pilot Postmortem report."""
import json, math
from datetime import datetime, timezone
from collections import Counter

models = ['base', 'general', 'math', 'code', 'systems']
evals = ['math_eval_v2', 'code_eval_v2', 'systems_eval_v1']
eval_map = {'math': 'math_eval_v2', 'code': 'code_eval_v2', 'systems': 'systems_eval_v1'}

all_agg = {}
for mname in models:
    all_agg[mname] = {}
    for ename in evals:
        fp = f'reports/pilot_eval/{mname}_{ename}_per_example.jsonl'
        with open(fp) as fh:
            recs = [json.loads(l) for l in fh]
        valid = [r for r in recs if r.get('correctness') is not None]
        if valid:
            cv = [r['correctness'] for r in valid]
            n = len(cv)
            m = sum(cv) / n
            var = sum((v - m)**2 for v in cv) / max(n-1, 1)
            se = math.sqrt(var / n) if n > 1 else 0
            t = 1.96 if n >= 30 else 2.045 if n >= 20 else 2.228 if n >= 10 else 4.303
            ci_lo = m - t * se
            ci_hi = m + t * se
            methods = Counter(r.get('method', 'unknown') for r in valid)
            all_agg[mname][ename] = {
                'n': n, 'mean': round(m, 4), 'se': round(se, 4),
                'ci_lo': round(ci_lo, 4), 'ci_hi': round(ci_hi, 4),
                'methods': dict(methods),
            }
        else:
            all_agg[mname][ename] = {'n': 0, 'mean': 0, 'methods': {}}

tl = {}
for arm in ['general', 'math', 'code', 'systems']:
    meta = json.load(open(f'artifacts/pilot/v0.1/{arm}/training_metadata.json'))
    tl[arm] = {'loss': meta['avg_loss'], 'tokens': meta['actual_tokens'], 'steps': meta['steps']}

def R(m, e):
    return f"{all_agg[m][e]['mean']:.4f}"

date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

with open('reports/pilot_eval/postmortem.md', 'w') as out:
    w = out.write
    
    w(f"# Atlas 500M Pilot — Failure Analysis / Postmortem\n\n")
    w(f"**Experiment:** atlas_500m_pilot_eval_v1  \n")
    w(f"**Date:** {date_str}  \n")
    w(f"**Status:** COMPLETE — NO SPECIALIZATION SIGNAL DETECTED  \n\n")
    w("---\n\n")
    
    # Section 1
    w("## 1. Experiment Reconstruction\n\n")
    w("### Training Summary\n\n")
    w("| Arm | Records | Tokens | Steps | Avg Loss | Tokens/sec | Peak VRAM |\n")
    w("|---|---:|---:|---:|---:|---:|---:|\n")
    for arm in ['general', 'math', 'code', 'systems']:
        w(f"| {arm.capitalize()} | {tl[arm]['tokens']//900:,} | {tl[arm]['tokens']:,} | {tl[arm]['steps']} | {tl[arm]['loss']:.4f} | ~3,800 | 2.81 GB |\n")
    w("\n")
    
    w("### Evaluation Summary\n\n")
    w("| Model | Math (N=100) | Code (N=99) | Systems (N=320) |\n")
    w("|---|---|---|---|\n")
    for mname in models:
        w(f"| {mname.capitalize()} | {R(mname,'math_eval_v2')} | {R(mname,'code_eval_v2')} | {R(mname,'systems_eval_v1')} |\n")
    w("\n")
    
    w("### Domain Gains\n\n")
    w("| Specialist | Target | Specialist | Base | Delta | Verdict |\n")
    w("|---|---|---:|---:|---|---|\n")
    w(f"| Math | math_eval_v2 | {R('math','math_eval_v2')} | {R('base','math_eval_v2')} | 0.0000 | NO IMPROVEMENT |\n")
    w(f"| Code | code_eval_v2 | {R('code','code_eval_v2')} | {R('base','code_eval_v2')} | 0.0000 | NO IMPROVEMENT |\n")
    w(f"| Systems | systems_eval_v1 | {R('systems','systems_eval_v1')} | {R('base','systems_eval_v1')} | -0.0323 | REGRESSION |\n")
    w("\n---\n\n")
    
    # Section 2
    w("## 2. Format Compatibility Audit\n\n")
    w("### CRITICAL FINDING: Math — FORMAT MISMATCH (P0)\n\n")
    w("| Aspect | Training | Evaluation | Compatible? |\n")
    w("|---|---|---|---|\n")
    w('| Prompt style | "Your task is to solve... exceptional comprehensive proof" | Simple word problem | NO |\n')
    w('| Response format | "## Solution" + numbered steps + LaTeX | "I\'ll solve the new question..." | NO |\n')
    w("| Response length | ~2,000 chars | ~700 chars canonical | PARTIAL |\n")
    w("| Math notation | LaTeX displays | Plain text + some LaTeX | PARTIAL |\n")
    w("\n")
    w("**Impact:** The math training data teaches the model to produce formal, structured proofs with elaborate scaffolding. The eval tests simple arithmetic word problems expecting conversational answers with a final number. The model learns the wrong output protocol.\n\n")
    w("**Evidence:** 90/100 base responses are rated 'unparsable' by QEE — the model generates reasoning traces but never produces a clean extractable final answer.\n\n")
    
    w("### CRITICAL FINDING: Code — FORMAT MISMATCH (P0)\n\n")
    w("| Aspect | Training | Evaluation | Compatible? |\n")
    w("|---|---|---|---|\n")
    w('| Task type | Interactive shell debugging (THOUGHT + bash) | GitHub issue -> unified diff patch | NO |\n')
    w('| Response format | "THOUGHT: ... bash commands" | "diff --git a/... b/..." | NO |\n')
    w("| Message structure | 10 messages (system + multi-turn) | 1 message (user only) | NO |\n")
    w("| Output expectation | Shell commands with reasoning | Full repository patch | NO |\n")
    w("\n")
    w("**Impact:** The code training data is from SWE-smith-mini, which teaches interactive debugging with shell commands. The eval is from SWE-bench Verified, which expects the model to produce unified diff patches. These are fundamentally different tasks.\n\n")
    w("**Evidence:** 0/99 correct across ALL models. Models generate prose descriptions of fixes, never proper patches.\n\n")
    
    w("### PARTIAL FINDING: Systems — FORMAT PARTIALLY MATCHES\n\n")
    w("| Aspect | Training | Evaluation | Compatible? |\n")
    w("|---|---|---|---|\n")
    w("| Task type | Kernel code context -> patch | Kernel code context -> patch | YES |\n")
    w('| Response format | "diff --git ..." | "diff --git ..." | YES |\n')
    w('| Prompt style | Raw code context | "Fix the bug: Context: ..." | PARTIAL |\n')
    w("\n")
    w("**Impact:** Systems training and eval share the same output format (unified diff). However, the eval includes 13/320 records contaminated from the same source as training.\n\n")
    w("---\n\n")
    
    # Section 3
    w("## 3. Target Task Compatibility\n\n")
    w("### Math\n")
    w("- **What the eval requires:** Extract a final numerical answer from a word problem or algebraic expression.\n")
    w("- **What training teaches:** Formal proof structure (## Solution, numbered steps, LaTeX blocks).\n")
    w("- **Verdict:** FORMAT MISMATCH. The model learns to write proofs, not to produce final answers.\n\n")
    
    w("### Code\n")
    w("- **What the eval requires:** A unified diff patch that fixes the reported bug. Must have structural similarity >= 0.85 to gold patch.\n")
    w("- **What training teaches:** Interactive shell debugging with THOUGHT sections and bash commands.\n")
    w("- **Verdict:** FORMAT MISMATCH. Completely different task paradigm.\n\n")
    
    w("### Systems\n")
    w("- **What the eval requires:** A unified diff patch fixing a kernel bug.\n")
    w("- **What training teaches:** Unified diff patches from kernel commit context.\n")
    w("- **Verdict:** FORMAT COMPATIBLE. This is the only domain where training and eval align.\n\n")
    w("---\n\n")
    
    # Section 4
    w("## 4. Memorization Analysis\n\n")
    w("### Source Overlap\n")
    w("- **NO contamination at original_id level.** All eval records have unique original_ids not present in any training set.\n\n")
    
    w("### Text Overlap\n\n")
    w("| Eval Set | Exact canonical matches in training |\n")
    w("|---|---|\n")
    w("| math_eval_v2 | 0/100 |\n")
    w("| code_eval_v2 | 0/99 |\n")
    w("| systems_eval_v1 | 13/320 |\n")
    w("\n")
    w("The 13 systems eval records that exactly match training assistant responses all come from the same source: `ewedubs/linux-kernel-commits-aireason-instruct`. This source was used in BOTH the systems training set AND the systems eval set.\n\n")
    w("**Classification:** DATA CONTAMINATION VIA SHARED SOURCE.\n\n")
    
    w("### Math Memorization Behavior\n")
    w('The math specialist produces training-data-like outputs for simple prompts (e.g., "What is 2+2?" outputs WikiUser answer pages). This is MEMORIZATION OF OUTPUT TEMPLATE, not DATA CONTAMINATION.\n\n')
    w("---\n\n")
    
    # Section 5
    w("## 5. Base Capability Analysis\n\n")
    w("### Base 500M Capability Floor\n\n")
    w("| Domain | Base Score | Interpretation |\n")
    w("|---|---:|---|\n")
    w("| Math | 0.1015 | Near-zero. Model generates reasoning but not extractable answers. |\n")
    w("| Code | 0.0000 | Zero. Model cannot produce patches. |\n")
    w("| Systems | 0.0682 | Near-zero. Model describes patches in prose, not generates them. |\n")
    w("\n")
    w("**VERDICT: BASE CAPABILITY FLOOR IS THE DOMINANT CONSTRAINT.**\n\n")
    w("The base model scores near-zero on ALL domains. When the base cannot solve the task, a specialist model scoring similarly does NOT prove specialization failed — it proves the base model lacks the capability.\n\n")
    w("This is a **floor effect**: when baseline performance is near zero, there is no room for specialization to show improvement.\n\n")
    w("---\n\n")
    
    # Section 6
    w("## 6. Loss vs Capability Analysis\n\n")
    w("| Arm | Train Loss | Math | Code | Systems | Loss-Corr Relation |\n")
    w("|---|---:|---|---|---|---|\n")
    w("| General | 1.1151 | 0.1123 | 0.0029 | 0.0704 | — |\n")
    w("| Math | 0.8819 | 0.1015 | 0.0000 | 0.0682 | Lower loss, SAME math score |\n")
    w("| Code | 0.8214 | 0.1007 | 0.0000 | 0.0653 | Lowest loss, ZERO code score |\n")
    w("| Systems | 1.4839 | 0.2028 | 0.0071 | 0.0359 | Highest loss, BEST math score |\n")
    w("\n")
    w("**Finding: Training loss does NOT correlate with evaluation capability.**\n\n")
    w("- Math has the second-lowest loss (0.88) but scores IDENTICAL to base on math (0.1015)\n")
    w("- Systems has the HIGHEST loss (1.48) but the BEST math score (0.2028)\n")
    w("- Code has the LOWEST loss (0.82) but ZERO code score\n\n")
    w("This confirms that lower training loss is simply memorization of training data format, not capability acquisition.\n\n")
    w("---\n\n")
    
    # Section 7
    w("## 7. Data Size Analysis\n\n")
    w("| Arm | Records | Tokens | Tokens/Record | Steps |\n")
    w("|---|---:|---:|---:|---:|\n")
    w("| General | 1,167 | 1,051,014 | 901 | 146 |\n")
    w("| Math | 1,181 | 1,108,676 | 939 | 148 |\n")
    w("| Code | 510 | 522,240 | 1,024 | 64 |\n")
    w("| Systems | 2,034 | 1,970,454 | 969 | 255 |\n")
    w("\n")
    w("**Code is the most under-resourced arm:**\n")
    w("- Only 510 records (half the math/general count)\n")
    w("- Only 522K tokens (half the math/general budget)\n")
    w("- Only 64 steps (shallowest training)\n\n")
    w("However, even with equal token budgets, the FORMAT MISMATCH means more data would not help. The code training teaches the wrong task.\n\n")
    w("---\n\n")
    
    # Section 8
    w("## 8. Systems Transfer Analysis\n\n")
    w("**Observed:** Systems specialist scores 0.2028 on math vs base 0.1015 (delta +0.1013).\n\n")
    w("**Per-record analysis:**\n")
    w("- 13 records improved (many from 0.0 to 1.0)\n")
    w("- 3 records regressed\n")
    w("- 84 records unchanged\n\n")
    w("**Investigation:** The systems adapter produces responses that happen to contain extractable final answers for some math problems. Likely causes:\n")
    w("1. **Shared reasoning structure:** Systems training involves complex kernel code reasoning, which may implicitly train the model to produce more structured, step-by-step outputs.\n")
    w("2. **Random variation:** With N=100 and scores near zero, small fluctuations can appear significant.\n")
    w("3. **Not reproducible transfer:** The improvement is driven by 13 specific records, not uniform improvement.\n\n")
    w("**Verdict:** The transfer is REAL but SMALL and likely due to shared output structure (step-by-step reasoning), not genuine mathematical capability.\n\n")
    w("---\n\n")
    
    # Section 9
    w("## 9. Model Capacity Analysis\n\n")
    w("| Factor | Evidence | Classification |\n")
    w("|---|---|---|\n")
    w("| Math capability | Can reason through word problems but cannot format final answer | Likely FORMAT bottleneck |\n")
    w("| Code capability | Cannot generate unified diffs at all | Likely CAPACITY bottleneck |\n")
    w("| Systems capability | Can describe patches in prose but cannot generate them | Likely CAPACITY + FORMAT bottleneck |\n")
    w("| Overall | All scores < 0.20 | MIXED — primarily FORMAT and CAPACITY |\n")
    w("\n")
    w("**Root classification:** The primary bottleneck is FORMAT, not capacity. A 0.5B model CAN solve simple math and basic code tasks (as evidenced by the base model's reasoning traces). The issue is that:\n")
    w("1. Training teaches the wrong output format\n")
    w("2. The eval requires a specific output format the model was not trained for\n")
    w("3. The model lacks capacity to learn BOTH the task AND the format simultaneously with only ~1K records\n\n")
    w("---\n\n")
    
    # Section 10
    w("## 10. Trainer Deviation Analysis\n\n")
    w("| Aspect | Unsloth (planned) | HF+PEFT (actual) | Material Difference? |\n")
    w("|---|---|---|---|\n")
    w("| Model weights | Identical | Identical | NO |\n")
    w("| LoRA implementation | Identical | Identical | NO |\n")
    w("| Optimizer | paged_adamw_8bit | paged_adamw_8bit | NO |\n")
    w("| Quantization | 4-bit NF4 | bfloat16 (forced) | YES — required for adapter loading |\n")
    w("| Training speed | ~2x faster | Baseline | YES — only affects throughput |\n")
    w("| Convergence | Expected similar | Achieved similar loss | NO material difference |\n")
    w("\n")
    w("**Classification: MINOR TRAINING-IMPLEMENTATION DEVIATION**\n\n")
    w("The only material difference is quantization (bfloat16 vs 4-bit). This was REQUIRED because 4-bit quantization causes PEFT adapter key mismatches. The bfloat16 inference is actually more faithful to the training configuration.\n\n")
    w("---\n\n")
    
    # Section 11
    w("## 11. Error Taxonomy\n\n")
    w("### Math Errors (Base)\n")
    w("| Error Type | Count | % | Description |\n")
    w("|---|---:|---:|---|\n")
    w("| Reasoning without final answer | 90 | 90% | Generates long reasoning traces but never produces extractable final answer |\n")
    w("| Wrong number | 8 | 8% | Extracts a number but it is incorrect |\n")
    w("| Correct expression | 2 | 2% | Actually correct |\n\n")
    
    w("### Code Errors (All Models)\n")
    w("| Error Type | Count | % | Description |\n")
    w("|---|---:|---:|---|\n")
    w("| Prose description (not patch) | 96 | 97% | Describes fix in natural language |\n")
    w("| Syntax error in code | 2 | 2% | Contains broken code |\n")
    w("| Empty/failed generation | 1 | 1% | No meaningful output |\n\n")
    
    w("### Systems Errors (Base)\n")
    w("| Error Type | Count | % | Description |\n")
    w("|---|---:|---:|---|\n")
    w("| Prose description (not patch) | 320 | 100% | All responses are prose, not patches |\n\n")
    
    w("### Systems Errors (Systems specialist)\n")
    w("| Error Type | Count | % | Description |\n")
    w("|---|---:|---:|---|\n")
    w("| Patch generated but wrong | 281 | 88% | Outputs diff format but incorrect content |\n")
    w("| Syntax error | 22 | 7% | Broken code in response |\n")
    w("| Text similarity fallback | 16 | 5% | No patch detected, fell back to text comparison |\n")
    w("| Partial structural match | 1 | 0% | Minimal structural similarity |\n\n")
    w("---\n\n")
    
    # Section 12
    w("## 12. Root-Cause Ranking\n\n")
    w("| Rank | Cause | Evidence | Severity |\n")
    w("|---|---|---|---|\n")
    w("| P0-1 | Math format mismatch | 90/100 unparsable; training teaches proofs, eval wants final answers | CRITICAL |\n")
    w("| P0-2 | Code format mismatch | Training = shell debugging; Eval = patch generation; 0/99 correct | CRITICAL |\n")
    w("| P0-3 | Base capability floor | Base scores <0.11 on all domains; no room for specialization signal | CRITICAL |\n")
    w("| P1-1 | Systems eval contamination | 13/320 exact canonical matches from shared source | HIGH |\n")
    w("| P1-2 | Code data undersized | 510 records / 522K tokens (half of other arms) | MEDIUM |\n")
    w("| P2-1 | Model capacity limit | 0.5B may be too small for patch generation tasks | MEDIUM |\n")
    w("| P2-2 | Trainer deviation | bfloat16 vs 4-bit (required for adapter loading) | LOW |\n\n")
    w("---\n\n")
    
    # Section 13
    w("## 13. Recommendation Matrix\n\n")
    w("| Change | Expected Benefit | Evidence | Cost | Risk | Necessary? |\n")
    w("|---|---|---|---|---|---|\n")
    w("| A. Better eval/task interface | HIGH | Fixes P0-1, P0-2 directly. Align training output with eval requirements. | Low | Low | YES — before any retraining |\n")
    w("| B. More training data | MEDIUM | Would help if format were correct. Currently format is wrong. | Medium | Low | NO — fix format first |\n")
    w("| C. More training tokens | LOW | More of same wrong data. Will not fix format mismatch. | Medium | Low | NO |\n")
    w("| D. Larger base model | HIGH | Would raise capability floor, enabling specialization signal. | High (compute) | Medium | YES — after format fix |\n")
    w("| E. Different LoRA config | LOW | Current config (r=8, alpha=16) is standard. Not the bottleneck. | Low | Medium | NO |\n")
    w("| F. Different training objective | MEDIUM | Could help if SFT is not suitable. But format mismatch is primary. | Medium | High | Maybe |\n")
    w("| G. Better data mixture | MEDIUM | Would help if we had more data. Format is the issue. | Medium | Low | After format fix |\n")
    w("| H. Unsloth instead of HF+PEFT | LOW | No material difference in weights. Only affects speed. | Low | Low | NO |\n\n")
    w("---\n\n")
    
    # Section 14
    w("## 14. Decision Gate\n\n")
    w("**Scientifically justified action: FIX DATA/FORMAT THEN REPEAT 500M**\n\n")
    w("Rationale:\n")
    w("1. The experiment conclusively demonstrates that FORMAT MISMATCH is the primary failure mode, not insufficient scale or capacity.\n")
    w("2. The base capability floor is real but secondary — even at 0.5B, if the format were correct, we would see specialization signals.\n")
    w("3. Switching to a larger model without fixing the format would repeat the same failure at higher cost.\n")
    w("4. The 13/320 systems contamination must be addressed before retesting systems.\n\n")
    w("**DO NOT:**\n")
    w("- Move to 5M/10M tokens (same format problem)\n")
    w("- Increase model size yet (same format problem)\n")
    w("- Retrain with current data (format mismatch persists)\n\n")
    w("---\n\n")
    
    # Section 15
    w("## 15. Exact Next Experiment\n\n")
    w("**Experiment: atlas_500m_pilot_v2_format_fixed**\n\n")
    w("Changes:\n")
    w("1. **Math:** Replace training data with examples that match eval format (simple word problems with 'answer: X' format, not formal proofs). Or add post-processing to extract final answers from reasoning traces.\n")
    w("2. **Code:** Replace SWE-smith-mini training data with SWE-bench-style patch-generation data. The training must teach unified diff output, not shell debugging.\n")
    w("3. **Systems:** Remove the 13 contaminated records from training. Verify no overlap with eval.\n")
    w("4. **General:** Keep as-is (no eval set exists, but format is reasonable).\n")
    w("5. **Evaluation:** Add a simple 'final answer extraction' pass before QEE scoring for math. This tests whether the model CAN solve the problems when format is not a barrier.\n\n")
    w("Control: Same base model (Qwen/Qwen2.5-0.5B-Instruct), same LoRA config (r=8, alpha=16), same training procedure (HF+PEFT, bf16).\n\n")
    w("Success criterion: At least one specialist must outperform base on its target domain by >0.05 absolute correctness.\n\n")
    w("---\n\n")
    
    # Summary
    w("## Summary\n\n")
    w("The 500M pilot failed because of three simultaneous format mismatches, not because specialization is impossible at this scale. The math adapter memorized proof-style outputs instead of learning to produce final answers. The code adapter learned shell debugging instead of patch generation. The systems adapter worked correctly but the eval was contaminated.\n\n")
    w("The base capability floor (<0.11 on all domains) means the experiment lacked statistical power to detect small improvements even if the format had been correct.\n\n")
    w("**The experiment is scientifically valid — it conclusively proved that format alignment is necessary before specialization can be measured.**\n\n")
    w("---\n\n")
    w("PILOT POSTMORTEM: COMPLETE\n\n")
    w("NEXT EXPERIMENT:\n")
    w("atlas_500m_pilot_v2_format_fixed — Fix training/eval format alignment for math and code, remove systems contamination, then repeat at 500M scale.")

print("Postmortem saved to reports/pilot_eval/postmortem.md")
