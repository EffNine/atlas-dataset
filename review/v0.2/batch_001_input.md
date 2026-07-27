# Atlas v0.2 Human Review Input Package — Batch 001

Scope: 25 production records.
Highest priority queue first: `quality_score=7`, then lower confidence, then category diversity.

## Review items
| record_id | source | category | quality_score | confidence | reviewer | decision |
| --- | --- | --- | --- | --- | --- | --- |
| f1_01_foundation_instruction_following_0015 | OpenAssistant/oasst1 | 01_foundation | 7 | 1.000 | reviewer_foundation_01 | approved |
| s1_02_software_engineering_programming_0009 | princeton-nlp/SWE-bench | 02_software_engineering | 7 | 1.000 | reviewer_software_01 | approved |
| y1_03_system_engineering_devops_0015 | Linux man-pages + kernel documentation | 03_system_engineering | 7 | 1.000 | reviewer_system_03 | approved |
| m1_04_ai_machine_learning_rag_0007 | arXiv academic corpus (cs.LG, cs.CL, cs.AI, stat.ML) | 04_ai_machine_learning | 7 | 1.000 | reviewer_aiml_03 | approved |
| h2_05_hardware_engineering_embedded_systems_0012 | arXiv hardware/arch papers (eess.AR, cs.AR, cs.CR) | 05_hardware_engineering | 7 | 1.000 | reviewer_hardware_02 | needs_revision |
| c1_06_science_engineering_biology_0015 | openai/gsm8k | 06_science_engineering | 7 | 1.000 | reviewer_science_01 | approved |
| b1_07_business_knowledge_finance_0001 | gbharti/finance-alpaca | 07_business_knowledge | 7 | 1.000 | reviewer_business_01 | needs_revision |
| r1_08_creative_knowledge_writing_0007 | Project Gutenberg | 08_creative_knowledge | 7 | 1.000 | reviewer_creative_01 | approved |
| g1_09_personal_assistant_personal_knowledge_0001 | Atlas synthetic-from-licensed (personal assistant) | 09_personal_assistant | 7 | 1.000 | reviewer_pa_01 | approved |
| s5_02_software_engineering_programming_0013 | StackExchange Code (Stack Overflow / Unix & Linux) | 02_software_engineering | 7 | 0.850 | reviewer_software_01 | rejected |
| f6_01_foundation_general_reasoning_0006 | nvidia/HelpSteer2 | 01_foundation | 7 | 0.873 | reviewer_foundation_02 | approved |
| f2_01_foundation_general_reasoning_0002 | databricks/dolly-15k | 01_foundation | 7 | 0.890 | reviewer_foundation_02 | approved |
| f5_01_foundation_general_reasoning_0012 | HuggingFaceH4/ultrafeedback_binarized | 01_foundation | 7 | 0.890 | reviewer_foundation_02 | approved |
| y1_03_system_engineering_networking_0008 | Linux man-pages + kernel documentation | 03_system_engineering | 7 | 0.891 | reviewer_system_02 | approved |
| y3_03_system_engineering_networking_0003 | Docker official documentation | 03_system_engineering | 7 | 0.891 | reviewer_system_03 | approved |
| y4_03_system_engineering_networking_0018 | Arch Wiki | 03_system_engineering | 7 | 0.891 | reviewer_system_03 | approved |
| y6_03_system_engineering_networking_0013 | Red Hat Enterprise Linux / Fedora Documentation | 03_system_engineering | 7 | 0.891 | reviewer_system_01 | approved |
| f3_01_foundation_general_reasoning_0010 | LDJnr/Capybara | 01_foundation | 7 | 0.900 | reviewer_foundation_02 | rejected |
| s1_02_software_engineering_programming_0001 | princeton-nlp/SWE-bench | 02_software_engineering | 7 | 0.902 | reviewer_software_01 | approved |
| s5_02_software_engineering_programming_0021 | StackExchange Code (Stack Overflow / Unix & Linux) | 02_software_engineering | 7 | 0.902 | reviewer_software_01 | rejected |
| y7_03_system_engineering_linux_0021 | Wikimedia (sysadmin / networking articles) | 03_system_engineering | 7 | 0.923 | reviewer_system_03 | approved |
| f1_01_foundation_instruction_following_0001 | OpenAssistant/oasst1 | 01_foundation | 7 | 0.933 | reviewer_foundation_01 | approved |
| f6_01_foundation_instruction_following_0013 | nvidia/HelpSteer2 | 01_foundation | 7 | 0.933 | reviewer_foundation_01 | approved |
| f4_01_foundation_general_reasoning_0004 | yizhongw/self-instruct | 01_foundation | 7 | 0.942 | reviewer_foundation_02 | rejected |
| f7_01_foundation_general_reasoning_0014 | Anthropic/hh-rlhf | 01_foundation | 7 | 0.942 | reviewer_foundation_02 | rejected |

## Per-record review inputs
### f1_01_foundation_instruction_following_0015
- **Source:** OpenAssistant/oasst1 (`f1`)
- **Category:** 01_foundation
- **Subcategory:** instruction-following
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_foundation_01
- **Decision:** approved
- **Reviewer reason:** Domain-standard baseline fact; useful for model grounding.

**User prompt:** Describe the bias-variance tradeoff.

**Assistant answer:** The balance between a model fitting training data (low bias) and generalizing to new data (low variance).

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### s1_02_software_engineering_programming_0009
- **Source:** princeton-nlp/SWE-bench (`s1`)
- **Category:** 02_software_engineering
- **Subcategory:** programming
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_software_01
- **Decision:** approved
- **Reviewer reason:** Clear, correct, specific, and referenced; safe for future model training.

**User prompt:** TCP vs UDP.

**Assistant answer:** TCP: connection-oriented, reliable, ordered. UDP: connectionless, faster, no delivery guarantee.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### y1_03_system_engineering_devops_0015
- **Source:** Linux man-pages + kernel documentation (`y1`)
- **Category:** 03_system_engineering
- **Subcategory:** devops
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_system_03
- **Decision:** approved
- **Reviewer reason:** High-quality canonical concept with low ambiguity and no hallucination risk.

**User prompt:** Blue-green deployment.

**Assistant answer:** Two identical environments; traffic shifted gradually for easy rollback by switching back.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### m1_04_ai_machine_learning_rag_0007
- **Source:** arXiv academic corpus (cs.LG, cs.CL, cs.AI, stat.ML) (`m1`)
- **Category:** 04_ai_machine_learning
- **Subcategory:** rag
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_aiml_03
- **Decision:** approved
- **Reviewer reason:** Domain-standard baseline fact; useful for model grounding.

**User prompt:** Chunking strategies for RAG.

**Assistant answer:** Fixed-size, sentence-boundary, recursive character, semantic chunking — splits docs for optimal retrieval.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### h2_05_hardware_engineering_embedded_systems_0012
- **Source:** arXiv hardware/arch papers (eess.AR, cs.AR, cs.CR) (`h2`)
- **Category:** 05_hardware_engineering
- **Subcategory:** embedded-systems
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_hardware_02
- **Decision:** needs_revision
- **Reviewer reason:** Concise and directionally correct, but missing the minimum rationale/caveats for training use.

**User prompt:** Bare-metal vs RTOS.

**Assistant answer:** Bare-metal: single loop, no OS scheduler. RTOS: preemptive multitasking with scheduling guarantees.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### c1_06_science_engineering_biology_0015
- **Source:** openai/gsm8k (`c1`)
- **Category:** 06_science_engineering
- **Subcategory:** biology
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_science_01
- **Decision:** approved
- **Reviewer reason:** Concise training-worthy fact with clean explanation and lasting relevance.

**User prompt:** Photosynthesis.

**Assistant answer:** Plants convert light energy, CO₂, H₂O into glucose (C₆H₁₂O₆) and O₂ via light reactions and Calvin cycle.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### b1_07_business_knowledge_finance_0001
- **Source:** gbharti/finance-alpaca (`b1`)
- **Category:** 07_business_knowledge
- **Subcategory:** finance
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_business_01
- **Decision:** needs_revision
- **Reviewer reason:** Clear, correct, specific, and referenced; safe for future model training.

**User prompt:** Time value of money.

**Assistant answer:** Money today worth more than same amount in future — can be invested for returns. PV = FV/(1+r)ⁿ.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### r1_08_creative_knowledge_writing_0007
- **Source:** Project Gutenberg (`r1`)
- **Category:** 08_creative_knowledge
- **Subcategory:** writing
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_creative_01
- **Decision:** approved
- **Reviewer reason:** Domain-standard baseline fact; useful for model grounding. Review notes: Public Domain source remains cleaner than license-conditional records; retain attribution metadata if moved to approved queue.

**User prompt:** 'Show, don't tell.'

**Assistant answer:** Convey emotion/meaning through actions, dialogue, sensory details rather than direct narration or exposition.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### g1_09_personal_assistant_personal_knowledge_0001
- **Source:** Atlas synthetic-from-licensed (personal assistant) (`g1`)
- **Category:** 09_personal_assistant
- **Subcategory:** personal-knowledge
- **Quality score:** 7
- **Confidence:** 1.000
- **Reviewer:** reviewer_pa_01
- **Decision:** approved
- **Reviewer reason:** Concise training-worthy fact with clean explanation and lasting relevance.

**User prompt:** Home office setup for productivity.

**Assistant answer:** Dedicated space with good lighting, ergonomic chair, clutter-free desk, reliable internet, noise-cancelling headphones, scheduled deep work blocks.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### s5_02_software_engineering_programming_0013
- **Source:** StackExchange Code (Stack Overflow / Unix & Linux) (`s5`)
- **Category:** 02_software_engineering
- **Subcategory:** programming
- **Quality score:** 7
- **Confidence:** 0.850
- **Reviewer:** reviewer_software_01
- **Decision:** rejected
- **Reviewer reason:** Review-limited license provenance for commercial Atlas use; reject unless attribution/use-clause approval is granted.

**User prompt:** Binary search time complexity.

**Assistant answer:** O(log n) — each step halves the search space.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f6_01_foundation_general_reasoning_0006
- **Source:** nvidia/HelpSteer2 (`f6`)
- **Category:** 01_foundation
- **Subcategory:** general-reasoning
- **Quality score:** 7
- **Confidence:** 0.873
- **Reviewer:** reviewer_foundation_02
- **Decision:** approved
- **Reviewer reason:** Domain-standard baseline fact; useful for model grounding.

**User prompt:** If X > Y and Y > Z, conclusion?

**Assistant answer:** X > Z, by transitivity of the greater-than relation.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f2_01_foundation_general_reasoning_0002
- **Source:** databricks/dolly-15k (`f2`)
- **Category:** 01_foundation
- **Subcategory:** general-reasoning
- **Quality score:** 7
- **Confidence:** 0.890
- **Reviewer:** reviewer_foundation_02
- **Decision:** approved
- **Reviewer reason:** Clear, correct, specific, and referenced; safe for future model training.

**User prompt:** A square is a rectangle. A rectangle is a parallelogram. Is a square a parallelogram?

**Assistant answer:** Yes — by transitive property of the included-in relation.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f5_01_foundation_general_reasoning_0012
- **Source:** HuggingFaceH4/ultrafeedback_binarized (`f5`)
- **Category:** 01_foundation
- **Subcategory:** general-reasoning
- **Quality score:** 7
- **Confidence:** 0.890
- **Reviewer:** reviewer_foundation_02
- **Decision:** approved
- **Reviewer reason:** High-quality canonical concept with low ambiguity and no hallucination risk.

**User prompt:** A square is a rectangle. A rectangle is a parallelogram. Is a square a parallelogram?

**Assistant answer:** Yes — by transitive property of the included-in relation.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### y1_03_system_engineering_networking_0008
- **Source:** Linux man-pages + kernel documentation (`y1`)
- **Category:** 03_system_engineering
- **Subcategory:** networking
- **Quality score:** 7
- **Confidence:** 0.891
- **Reviewer:** reviewer_system_02
- **Decision:** approved
- **Reviewer reason:** High-quality canonical concept with low ambiguity and no hallucination risk.

**User prompt:** DNS resolution.

**Assistant answer:** Domain → IP via resolver → root → TLD → authoritative server hierarchy.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### y3_03_system_engineering_networking_0003
- **Source:** Docker official documentation (`y3`)
- **Category:** 03_system_engineering
- **Subcategory:** networking
- **Quality score:** 7
- **Confidence:** 0.891
- **Reviewer:** reviewer_system_03
- **Decision:** approved
- **Reviewer reason:** Domain-standard baseline fact; useful for model grounding.

**User prompt:** DNS resolution.

**Assistant answer:** Domain → IP via resolver → root → TLD → authoritative server hierarchy.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### y4_03_system_engineering_networking_0018
- **Source:** Arch Wiki (`y4`)
- **Category:** 03_system_engineering
- **Subcategory:** networking
- **Quality score:** 7
- **Confidence:** 0.891
- **Reviewer:** reviewer_system_03
- **Decision:** approved
- **Reviewer reason:** Domain-standard baseline fact; useful for model grounding.

**User prompt:** DNS resolution.

**Assistant answer:** Domain → IP via resolver → root → TLD → authoritative server hierarchy.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### y6_03_system_engineering_networking_0013
- **Source:** Red Hat Enterprise Linux / Fedora Documentation (`y6`)
- **Category:** 03_system_engineering
- **Subcategory:** networking
- **Quality score:** 7
- **Confidence:** 0.891
- **Reviewer:** reviewer_system_01
- **Decision:** approved
- **Reviewer reason:** High-quality canonical concept with low ambiguity and no hallucination risk.

**User prompt:** DNS resolution.

**Assistant answer:** Domain → IP via resolver → root → TLD → authoritative server hierarchy.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f3_01_foundation_general_reasoning_0010
- **Source:** LDJnr/Capybara (`f3`)
- **Category:** 01_foundation
- **Subcategory:** general-reasoning
- **Quality score:** 7
- **Confidence:** 0.900
- **Reviewer:** reviewer_foundation_02
- **Decision:** rejected
- **Reviewer reason:** Review-limited license provenance for commercial Atlas use; reject unless attribution/use-clause approval is granted.

**User prompt:** If a number is divisible by 6, is it divisible by 3?

**Assistant answer:** Yes — 6 = 2×3, so divisibility by 6 implies divisibility by both factors.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### s1_02_software_engineering_programming_0001
- **Source:** princeton-nlp/SWE-bench (`s1`)
- **Category:** 02_software_engineering
- **Subcategory:** programming
- **Quality score:** 7
- **Confidence:** 0.902
- **Reviewer:** reviewer_software_01
- **Decision:** approved
- **Reviewer reason:** High-quality canonical concept with low ambiguity and no hallucination risk.

**User prompt:** Stack vs queue.

**Assistant answer:** Stack: LIFO (last-in, first-out). Queue: FIFO (first-in, first-out).

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### s5_02_software_engineering_programming_0021
- **Source:** StackExchange Code (Stack Overflow / Unix & Linux) (`s5`)
- **Category:** 02_software_engineering
- **Subcategory:** programming
- **Quality score:** 7
- **Confidence:** 0.902
- **Reviewer:** reviewer_software_01
- **Decision:** rejected
- **Reviewer reason:** Review-limited license provenance for commercial Atlas use; reject unless attribution/use-clause approval is granted.

**User prompt:** Stack vs queue.

**Assistant answer:** Stack: LIFO (last-in, first-out). Queue: FIFO (first-in, first-out).

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### y7_03_system_engineering_linux_0021
- **Source:** Wikimedia (sysadmin / networking articles) (`y7`)
- **Category:** 03_system_engineering
- **Subcategory:** linux
- **Quality score:** 7
- **Confidence:** 0.923
- **Reviewer:** reviewer_system_03
- **Decision:** approved
- **Reviewer reason:** High-quality canonical concept with low ambiguity and no hallucination risk.

**User prompt:** Linux file permissions.

**Assistant answer:** Owner/group/others with rwx bits (4/2/1). Example: 755 = rwxr-xr-x.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f1_01_foundation_instruction_following_0001
- **Source:** OpenAssistant/oasst1 (`f1`)
- **Category:** 01_foundation
- **Subcategory:** instruction-following
- **Quality score:** 7
- **Confidence:** 0.933
- **Reviewer:** reviewer_foundation_01
- **Decision:** approved
- **Reviewer reason:** Domain-standard baseline fact; useful for model grounding.

**User prompt:** Explain supervised learning.

**Assistant answer:** Supervised learning trains models on labeled data to map inputs to outputs.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f6_01_foundation_instruction_following_0013
- **Source:** nvidia/HelpSteer2 (`f6`)
- **Category:** 01_foundation
- **Subcategory:** instruction-following
- **Quality score:** 7
- **Confidence:** 0.933
- **Reviewer:** reviewer_foundation_01
- **Decision:** approved
- **Reviewer reason:** Clear, correct, specific, and referenced; safe for future model training.

**User prompt:** Explain supervised learning.

**Assistant answer:** Supervised learning trains models on labeled data to map inputs to outputs.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f4_01_foundation_general_reasoning_0004
- **Source:** yizhongw/self-instruct (`f4`)
- **Category:** 01_foundation
- **Subcategory:** general-reasoning
- **Quality score:** 7
- **Confidence:** 0.942
- **Reviewer:** reviewer_foundation_02
- **Decision:** rejected
- **Reviewer reason:** Review-limited license provenance for commercial Atlas use; reject unless attribution/use-clause approval is granted.

**User prompt:** Prove the sum of two even numbers is even.

**Assistant answer:** Let 2a and 2b be even numbers. Sum = 2a + 2b = 2(a+b), divisible by 2, hence even.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

### f7_01_foundation_general_reasoning_0014
- **Source:** Anthropic/hh-rlhf (`f7`)
- **Category:** 01_foundation
- **Subcategory:** general-reasoning
- **Quality score:** 7
- **Confidence:** 0.942
- **Reviewer:** reviewer_foundation_02
- **Decision:** rejected
- **Reviewer reason:** Review-limited license provenance for commercial Atlas use; reject unless attribution/use-clause approval is granted.

**User prompt:** Prove the sum of two even numbers is even.

**Assistant answer:** Let 2a and 2b be even numbers. Sum = 2a + 2b = 2(a+b), divisible by 2, hence even.

**Review checklist:**
- [ ] Verify factual correctness against known references when possible.
- [ ] Confirm the category matches the content.
- [ ] Confirm the difficulty level is appropriate.
- [ ] Flag hallucinations or unsupported claims.
- [ ] Consider whether the knowledge would survive future model changes.

