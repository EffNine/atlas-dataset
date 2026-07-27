#!/usr/bin/env python3
"""
generate_synthetic_test.py — Atlas pipeline validation fixture generator.

Produces a 100-record raw JSONL file that exercises every stage of the Atlas
pipeline with controlled defects:

  * 56 unique, valid records (full metadata, mixed quality tiers)
  * 10 exact duplicates  (content-identical to a unique record, distinct id)
  *  5 near duplicates   (minimal variation of a unique record)
  *  6 invalid records    (5 structurally invalid objects + 1 malformed JSON line)
  * 23 missing-metadata   (valid content, tags/source/notes omitted -> coerced)

The canonical category taxonomy uses prefixed IDs. The friendly names from the
task spec map as:
    software_engineering  -> 02_software_engineering
    system_engineering    -> 03_system_engineering
    ai_ml                 -> 04_ai_machine_learning
    hardware_engineering  -> 05_hardware_engineering
    general_reasoning     -> 01_foundation

This generator emits CANONICAL ids so the bulk of the pipeline is validated
end-to-end. The cleaner's handling of the raw friendly names is probed
separately (see tests/verify_pipeline.py / the test report).

A manifest JSON is written alongside the raw file so the verifier can assert
exact expectations (which exact-dup content hashes and near-dup ids must be
absent after dedup, which records should survive, etc.).

Usage:
  python tests/generate_synthetic_test.py
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "raw" / "generated"
MANIFEST = ROOT / "tests" / "synthetic_test_manifest.json"

# (friendly_name -> canonical_id) used only for documentation / mapping table
FRIENDLY_TO_CANON = {
    "software_engineering": "02_software_engineering",
    "system_engineering": "03_system_engineering",
    "ai_ml": "04_ai_machine_learning",
    "hardware_engineering": "05_hardware_engineering",
    "general_reasoning": "01_foundation",
}

SYSTEM_PROMPT = "You are Atlas, a precise and helpful AI assistant."

# ---------------------------------------------------------------------------
# Example pools. Each entry: sub, type, tags, user, good (long/structured),
# bad (terse). `good` drives high/medium quality; `bad` drives low quality.
# ---------------------------------------------------------------------------
EXAMPLES = {
    "02_software_engineering": [
        {"sub": "programming", "type": "qa", "tags": ["python", "recursion"],
         "user": "Write a Python function to flatten a nested list of arbitrary depth.",
         "good": "Use recursion: if an item is a list, recurse into it, otherwise yield the item.\n\n```python\ndef flatten(items):\n    for it in items:\n        if isinstance(it, list):\n            yield from flatten(it)\n        else:\n            yield it\n```\n\nThis preserves order and handles arbitrary nesting. For a non-generator version wrap it in `list(...)`.",
         "bad": "Use a list comprehension."},
        {"sub": "algorithms", "type": "qa", "tags": ["sorting", "complexity"],
         "user": "Explain quicksort's average and worst-case time complexity.",
         "good": "Quicksort averages O(n log n) because it splits the array roughly in half at each level and does linear partition work. Worst case is O(n^2) when the pivot is consistently the smallest or largest element (e.g. already-sorted input with a naive end-pivot). Randomizing the pivot or using median-of-three avoids the worst case in practice.",
         "bad": "It is O(n log n) on average."},
        {"sub": "debugging", "type": "qa", "tags": ["python", "indentation"],
         "user": "My Python loop returns after the first iteration instead of summing all items. Why?",
         "good": "The `return` is likely indented inside the loop, so it exits on the first pass. Unindent it to the function body level so the loop completes before returning. As a rule, `return` ends the function immediately, so its indentation controls the loop's lifetime.",
         "bad": "Your return is in the wrong place."},
        {"sub": "software-architecture", "type": "reasoning", "tags": ["microservices", "monolith"],
         "user": "When should I choose microservices over a monolith?",
         "good": "Start with a modular monolith. Move to microservices only when you have clear, independently deployable boundaries and the organizational overhead is justified — separate teams, different scaling profiles, or incompatible tech stacks. Microservices add network, ops, and data-consistency cost; adopt them for boundaries, not fashion.",
         "bad": "When you need to scale."},
        {"sub": "programming", "type": "qa", "tags": ["python", "io"],
         "user": "How do I read a very large file lazily in Python without loading it all into memory?",
         "good": "Iterate the file object directly; it yields one line at a time:\n\n```python\nwith open(path) as f:\n    for line in f:\n        process(line)\n```\n\nFor binary or chunked reads use `f.read(chunk_size)` in a loop. This keeps memory flat regardless of file size.",
         "bad": "Use a for loop."},
        {"sub": "algorithms", "type": "qa", "tags": ["graph", "traversal"],
         "user": "What is the difference between BFS and DFS?",
         "good": "BFS explores level by level using a queue and finds the shortest path in unweighted graphs; DFS goes deep first using a stack/recursion and is better for connectivity, topological order, and cycle detection. BFS uses more memory; DFS can get stuck in deep branches.",
         "bad": "BFS is breadth-first, DFS is depth-first."},
        {"sub": "debugging", "type": "qa", "tags": ["python", "indexerror"],
         "user": "I get IndexError when my list is empty. How do I fix it?",
         "good": "Guard against empty input before indexing: check `if not items:` early and return a sentinel or raise a clear error. Prefer `.pop()` / `next(iter(items), default)` over `items[0]` when the list may be empty, and add a unit test for the empty case.",
         "bad": "Check if the list is empty."},
        {"sub": "software-architecture", "type": "instruction", "tags": ["api", "idempotency"],
         "user": "How do I design an idempotent API endpoint?",
         "good": "Make repeated identical calls produce the same result. Use a client-supplied idempotency key, dedupe on the server, and perform writes with conditional/upsert semantics. Return the same success response on repeats instead of creating duplicates. This makes retries safe under network failures.",
         "bad": "Use an idempotency key."},
        {"sub": "programming", "type": "qa", "tags": ["python", "dict"],
         "user": "How do I merge two dictionaries in Python 3.9+?",
         "good": "Use the merge operator: `merged = a | b` (or `a |= b` in place). Later keys overwrite earlier ones. For a deeper merge of nested dicts you must recurse manually, since `|` only replaces top-level keys.",
         "bad": "Use a.update(b)."},
        {"sub": "algorithms", "type": "reasoning", "tags": ["dynamic-programming"],
         "user": "Explain dynamic programming using a concrete example.",
         "good": "DP solves problems by combining solutions to subproblems and storing them to avoid recomputation. Classic example: Fibonacci — instead of exponential recursion, memoize or build bottom-up: `dp[i] = dp[i-1] + dp[i-2]`. Identify overlapping subproblems and an optimal substructure, then choose top-down memoization or bottom-up tabulation.",
         "bad": "Store subproblem results."},
        {"sub": "debugging", "type": "qa", "tags": ["python", "async"],
         "user": "My async function prints a coroutine object instead of the value. Why?",
         "good": "You forgot to `await` it. An async function returns a coroutine; you must `await` it to get the result. Also ensure the call runs inside an event loop (e.g. `asyncio.run(main())`). Printing without `await` shows the coroutine, not its return value.",
         "bad": "You forgot await."},
        {"sub": "software-architecture", "type": "qa", "tags": ["patterns", "repository"],
         "user": "What is the repository pattern and when is it useful?",
         "good": "The repository pattern wraps data access behind a collection-like interface, decoupling domain logic from the database. It makes code testable (swap a fake repo in tests) and centralizes query logic. Use it when persistence details would otherwise leak into business logic, but skip it for trivial CRUD apps where it adds ceremony.",
         "bad": "It abstracts data access."},
        {"sub": "programming", "type": "instruction", "tags": ["python", "exceptions"],
         "user": "How do I handle exceptions cleanly without swallowing errors?",
         "good": "Catch the narrowest exception type you can handle, do something useful (log, retry, fallback), and re-raise or translate if you cannot. Avoid bare `except: pass`. Use `finally` for cleanup and context managers (`with`) to guarantee resource release.",
         "bad": "Use try/except."},
    ],
    "03_system_engineering": [
        {"sub": "linux", "type": "qa", "tags": ["linux", "disk"],
         "user": "How do I find disk usage per directory on Linux?",
         "good": "Use `du -h --max-depth=1 /path` for a human-readable per-directory summary, or `ncdu` for an interactive browser. To find the single largest directories quickly: `du -h /path | sort -h | tail`. Combine with `--exclude` to skip mounts like `/proc`.",
         "bad": "Use du."},
        {"sub": "docker", "type": "instruction", "tags": ["docker", "image-size"],
         "user": "How do I reduce a Docker image's size?",
         "good": "Use a slim base image, multi-stage builds to keep only runtime artifacts, and chain `apt`/`pip` installs with cleanup in one layer. Order layers from least to most frequently changing, use `.dockerignore`, and prefer `RUN ... && rm -rf /var/lib/apt/lists/*` to shrink layers.",
         "bad": "Use a smaller base image."},
        {"sub": "networking", "type": "qa", "tags": ["networking", "tcp", "udp"],
         "user": "What is the difference between TCP and UDP?",
         "good": "TCP is connection-oriented, reliable, and ordered (handshake, retransmission, flow control) — ideal for web/API traffic. UDP is connectionless and fire-and-forget with lower latency — ideal for live audio, gaming, and DNS. TCP costs overhead; UDP can drop or reorder packets.",
         "bad": "TCP is reliable, UDP is not."},
        {"sub": "kubernetes", "type": "qa", "tags": ["kubernetes", "rollback"],
         "user": "How do I roll back a Kubernetes deployment?",
         "good": "Run `kubectl rollout undo deployment/<name>` to revert to the previous ReplicaSet, or `kubectl rollout undo deployment/<name> --to-revision=N` for a specific one. Check status with `kubectl rollout status`. Keep history via `revisionHistoryLimit` and use readiness probes so rollbacks are safe.",
         "bad": "Use kubectl rollout undo."},
        {"sub": "linux", "type": "qa", "tags": ["linux", "monitoring"],
         "user": "How do I monitor open file descriptors on Linux?",
         "good": "Per-process: `ls /proc/<pid>/fd | wc -l` or `lsof -p <pid>`. System-wide: `cat /proc/sys/fs/file-nr` shows allocated/free. Watch for leaks with `watch -n1 'cat /proc/sys/fs/file-nr'` and raise `fs.file-max` if you approach the limit. Exhaustion causes 'too many open files' errors.",
         "bad": "Check /proc."},
        {"sub": "docker", "type": "qa", "tags": ["docker", "cmd", "entrypoint"],
         "user": "What is the difference between CMD and ENTRYPOINT in Docker?",
         "good": "ENTRYPOINT defines the executable that always runs; CMD supplies its default arguments. You can override CMD at run time but not ENTRYPOINT without `--entrypoint`. A common pattern is ENTRYPOINT as the binary and CMD as default flags, letting users append arguments cleanly.",
         "bad": "CMD is the default command."},
        {"sub": "networking", "type": "qa", "tags": ["networking", "dns"],
         "user": "How do I debug DNS resolution failures on a server?",
         "good": "Check `/etc/resolv.conf` for correct nameservers, then `dig +trace example.com` and `nslookup example.com` to see where resolution breaks. Verify firewall egress on port 53, try a public resolver (1.1.1.1), and inspect `systemd-resolved`/`nscd` caches. Capture with `tcpdump -n port 53` if needed.",
         "bad": "Check resolv.conf."},
        {"sub": "kubernetes", "type": "instruction", "tags": ["kubernetes", "resources"],
         "user": "How do I set CPU and memory limits on a Kubernetes pod?",
         "good": "Set `resources.requests` (scheduler guarantee) and `resources.limits` (hard cap) per container. Requests drive scheduling; limits prevent a container from eating the node. Always set both for production to enable the scheduler and avoid noisy-neighbor evictions.",
         "bad": "Set resources.limits."},
        {"sub": "linux", "type": "qa", "tags": ["linux", "cron"],
         "user": "How do I schedule a cron job to run every 15 minutes?",
         "good": "Add `*/15 * * * * /path/to/job.sh` to the user crontab via `crontab -e`. The five fields are minute, hour, day-of-month, month, day-of-week. Redirect output to a log and ensure the script has a shebang and executable bit. Validate with `crontab -l`.",
         "bad": "Use */15 * * * *."},
        {"sub": "docker", "type": "instruction", "tags": ["docker", "secrets"],
         "user": "How do I pass secrets to a container securely?",
         "good": "Use Docker/Kubernetes secrets or an external vault rather than baking them into the image or plain env vars. Mount secrets as files under `/run/secrets` and read them at runtime. Never commit them to source; scan images for leaked credentials in CI.",
         "bad": "Use environment variables."},
        {"sub": "networking", "type": "qa", "tags": ["networking", "nat"],
         "user": "Explain NAT in one paragraph.",
         "good": "Network Address Translation rewrites source/destination IPs and ports so many private hosts share one public address. A router maps internal (IP:port) to external (IP:port) in a translation table, forwarding replies back. It conserves IPv4 space and hides internal topology, at the cost of breaking some peer-to-peer protocols.",
         "bad": "It translates addresses."},
        {"sub": "kubernetes", "type": "qa", "tags": ["kubernetes", "probes"],
         "user": "What is the difference between a liveness and a readiness probe?",
         "good": "A liveness probe tells Kubernetes whether the container is alive; failure triggers a restart. A readiness probe tells whether the container can serve traffic; failure removes it from the Service endpoints without restarting. Use liveness for hung states and readiness for startup/warmup or dependency unavailability.",
         "bad": "Liveness restarts, readiness gates traffic."},
        {"sub": "linux", "type": "qa", "tags": ["linux", "find"],
         "user": "How do I find the largest files on a filesystem?",
         "good": "Use `find /path -type f -printf '%s %p\\n' | sort -rn | head -20` for byte sizes, or `du -ah /path | sort -rh | head`. For a whole disk, start at `/` and exclude virtual filesystems with `-x` to avoid `/proc`/`/sys`. Pipe to `numfmt --to=iec` for human-readable sizes.",
         "bad": "Use find with du."},
    ],
    "04_ai_machine_learning": [
        {"sub": "llm", "type": "qa", "tags": ["transformer", "attention"],
         "user": "What is the attention mechanism in transformers?",
         "good": "Attention lets each token weight every other token by relevance. Scaled dot-product attention computes scores from query/key dot products, scales by sqrt(d), applies softmax, and takes a weighted sum of values. This gives global, content-based context per token and replaces recurrence, enabling parallel training.",
         "bad": "It weighs tokens by relevance."},
        {"sub": "rag", "type": "qa", "tags": ["rag", "evaluation"],
         "user": "How do I evaluate the quality of RAG answers?",
         "good": "Measure retrieval with recall@k and context relevance, and generation with faithfulness (does the answer stay grounded in retrieved context) plus answer relevance. Use a labeled set and LLM-as-judge or embedding similarity against references. Track end-to-end with task-specific accuracy so changes are measurable, not anecdotal.",
         "bad": "Check if answers are correct."},
        {"sub": "transformers", "type": "reasoning", "tags": ["transformers", "positional"],
         "user": "Explain positional encoding in transformers.",
         "good": "Since attention is order-agnostic, positional encodings inject sequence order. Sinusoidal encodings (original paper) use fixed sin/cos curves at different frequencies so relative positions are recoverable; learned encodings are trained instead. Rotary (RoPE) rotates query/key vectors by position, now common in modern LLMs for length extrapolation.",
         "bad": "It encodes position."},
        {"sub": "mlops", "type": "qa", "tags": ["mlops", "versioning"],
         "user": "How do I version ML datasets reproducibly?",
         "good": "Treat data like code: store a hash or content-address of each dataset version, keep a manifest mapping version to exact row hashes, and log the split seed. Use DVC or a lake with immutable snapshots. Record the data version alongside the model version so any training run is reproducible end to end.",
         "bad": "Hash the dataset."},
        {"sub": "llm", "type": "qa", "tags": ["llm", "sampling", "temperature"],
         "user": "What does temperature do when sampling LLM output?",
         "good": "Temperature scales the logits before softmax. Low values (near 0) sharpen the distribution toward the most likely tokens (deterministic, focused); high values flatten it (diverse, risky). It controls creativity vs fidelity but does not change the model's knowledge — only the sampling sharpness.",
         "bad": "It controls randomness."},
        {"sub": "rag", "type": "qa", "tags": ["rag", "retrieval"],
         "user": "When should I use hybrid retrieval instead of dense-only?",
         "good": "Use hybrid (BM25 + dense) when queries contain exact keywords, IDs, or rare terms where lexical matching beats semantic similarity. Hybrid also helps with out-of-domain vocabulary and is more robust to embedding drift. Fuse with RRF or a reranker and A/B test against dense-only on your own queries.",
         "bad": "When keywords matter."},
        {"sub": "transformers", "type": "qa", "tags": ["transformers", "encoder", "decoder"],
         "user": "What is the difference between an encoder and a decoder transformer?",
         "good": "An encoder maps an input sequence to contextual representations (bidirectional attention) — used for classification/retrieval (BERT). A decoder generates tokens autoregressively with causal (masked) attention (GPT). Encoder-decoder hybrids (T5) use both for seq2seq. The attention mask is the key difference.",
         "bad": "Encoder understands, decoder generates."},
        {"sub": "mlops", "type": "qa", "tags": ["mlops", "drift"],
         "user": "How do I detect model drift in production?",
         "good": "Monitor input-feature distributions (population stability index), prediction distribution shift, and performance proxy metrics over time. Compare live embeddings/stats to the training baseline and alert on statistically significant divergence. Pair drift detection with scheduled evaluation on fresh labels to confirm real degradation before retraining.",
         "bad": "Compare distributions over time."},
        {"sub": "llm", "type": "reasoning", "tags": ["lora", "rank"],
         "user": "Explain what the rank means in LoRA.",
         "good": "LoRA injects a low-rank update `BA` (with `B` of shape d×r and `A` of r×k) into a weight matrix. The rank `r` bounds how many directions the adaptation can span: small `r` (1–8) captures broad patterns cheaply; larger `r` (16–64) adds capacity at a parameter cost. `r` is the main knob tradingexpressiveness against memory.",
         "bad": "It is the adaptation size."},
        {"sub": "rag", "type": "instruction", "tags": ["rag", "chunking"],
         "user": "How do I chunk documents effectively for RAG?",
         "good": "Prefer semantic or sentence-window chunking over fixed character cuts so context isn't split mid-thought. Keep chunks sized to your embedder's window (256–512 tokens typical) with slight overlap. Preserve structure (headings, tables) and store metadata for filtering. Evaluate chunk size against retrieval recall on real queries.",
         "bad": "Split into fixed-size chunks."},
        {"sub": "transformers", "type": "qa", "tags": ["transformers", "kv-cache"],
         "user": "What is the KV cache and why does it matter?",
         "good": "During autoregressive decoding, the key/value vectors for previous tokens are cached so each new step only computes the current token instead of re-attending to all history. This turns O(n^2) per token into O(n) and is essential for fast inference, though it grows with sequence length and bounds max context by VRAM.",
         "bad": "It caches keys and values."},
        {"sub": "mlops", "type": "instruction", "tags": ["mlops", "pipeline"],
         "user": "How do I set up a reproducible training pipeline?",
         "good": "Pin code (lockfile), data (versioned hash), and config (committed YAML). Drive runs from a single entrypoint with logged hyperparameters, seeds, and metrics to a tracker. Containerize the environment and store artifacts with run ids. Make every stage deterministic and re-runnable from a manifest so any model is reproducible weeks later.",
         "bad": "Use a config file."},
        {"sub": "llm", "type": "qa", "tags": ["llm", "in-context"],
         "user": "What is in-context learning in LLMs?",
         "good": "In-context learning is the model's ability to perform a task from examples or instructions in the prompt, without weight updates. Few-shot prompts demonstrate the pattern; the model generalizes from the context using its pretrained priors. It is powerful but sensitive to example order, formatting, and recency in the context window.",
         "bad": "Learning from the prompt."},
    ],
    "05_hardware_engineering": [
        {"sub": "gpu", "type": "qa", "tags": ["gpu", "utilization"],
         "user": "What is the difference between GPU utilization and memory utilization?",
         "good": "GPU utilization (from `nvidia-smi`) is the fraction of time over the last sample that one or more kernels was executing on the GPU — a compute-busy measure. Memory utilization is how much VRAM is allocated. High compute with low memory means compute-bound; low compute with high memory often means you are stalled on data movement or host overhead.",
         "bad": "One is compute, one is memory."},
        {"sub": "cpu", "type": "qa", "tags": ["cpu", "branch-prediction"],
         "user": "What is branch prediction and why does it matter?",
         "good": "Modern CPUs guess which branch a conditional will take to keep the pipeline full; a correct guess avoids a stall. Mispredictions flush the pipeline and cost cycles. Tight loops with predictable patterns predict well; random branches hurt. Arrange hot code to be branch-friendly and avoid data-dependent branching in inner loops.",
         "bad": "It guesses branches."},
        {"sub": "embedded-systems", "type": "instruction", "tags": ["embedded", "power"],
         "user": "How do I reduce power consumption on a microcontroller?",
         "good": "Lower the clock and voltage to the minimum the workload needs, use sleep/low-power modes between tasks, disable unused peripherals and clocks, and prefer DMA over CPU-polled I/O. Batch sensor reads and wake less often. Profile with a current probe to find the dominant consumer before optimizing.",
         "bad": "Use sleep mode."},
        {"sub": "firmware", "type": "qa", "tags": ["firmware", "bootloader"],
         "user": "What is a bootloader and what does it do?",
         "good": "A bootloader is the first code that runs on power-up; it initializes hardware, verifies and loads the main application, and often supports firmware updates and recovery. It may validate a signature before booting to prevent tampered images. A robust bootloader is critical for safe, field-updatable devices.",
         "bad": "It boots the device."},
        {"sub": "gpu", "type": "qa", "tags": ["gpu", "tensor-cores"],
         "user": "What are tensor cores and what are they for?",
         "good": "Tensor cores are specialized GPU units that perform mixed-precision matrix multiply-accumulate (e.g. FP16 inputs, FP32 accumulate) in one instruction. They massively accelerate training and inference of neural networks relative to regular FP32 cores, at some precision cost mitigated by techniques like loss scaling.",
         "bad": "They accelerate matrix math."},
        {"sub": "cpu", "type": "qa", "tags": ["cpu", "cache-coherency"],
         "user": "What is cache coherency and why is it hard?",
         "good": "Cache coherency ensures all cores see a consistent view of memory despite private caches. Protocols like MESI track line state and broadcast invalidations, which adds latency and traffic. False sharing — unrelated variables on one cache line — causes needless invalidations and is a classic multicore performance bug.",
         "bad": "It keeps caches consistent."},
        {"sub": "embedded-systems", "type": "qa", "tags": ["embedded", "hard-fault"],
         "user": "How do I debug a hard fault on an ARM microcontroller?",
         "good": "Capture the fault status registers (CFSR/HFSR) and the stacked PC/LR from the exception frame to find the offending instruction. Common causes are NULL derefs, unaligned access, and stack overflow. Use a debugger to inspect the saved registers, enable fault handlers early, and add a hard-fault handler that dumps context.",
         "bad": "Inspect the registers."},
        {"sub": "firmware", "type": "qa", "tags": ["firmware", "memory"],
         "user": "What is the difference between RAM and ROM?",
         "good": "RAM is volatile, fast, read-write memory used for runtime data and stack; it loses contents on power loss. ROM (or flash) is non-volatile, persists firmware and constants, and is typically written in larger blocks and slower. Modern firmware usually lives in flash (a ROM variant) that is rewritten in pages during updates.",
         "bad": "RAM is volatile, ROM is not."},
        {"sub": "gpu", "type": "qa", "tags": ["gpu", "bandwidth"],
         "user": "Why is memory bandwidth more important than FLOPS for training?",
         "good": "Transformer layers are memory-bound: each step reads weights and activations from VRAM far more than it computes. If bandwidth starves the cores, FLOPS are wasted. That is why HBM and high-bandwidth buses (NVLink) often dictate real throughput more than peak TFLOPS, especially at large batch sizes.",
         "bad": "Bandwidth feeds the cores."},
        {"sub": "cpu", "type": "qa", "tags": ["cpu", "simd"],
         "user": "What is SIMD and where does it help?",
         "good": "SIMD (Single Instruction Multiple Data) applies one operation to many data elements in parallel via wide registers (SSE/AVX/NEON). It accelerates loops over arrays — image processing, DSP, vector math — where the same op repeats. It does not help branching or pointer-chasing code; compilers auto-vectorize friendly loops.",
         "bad": "It processes many items at once."},
        {"sub": "embedded-systems", "type": "qa", "tags": ["embedded", "rtos"],
         "user": "What is an RTOS and when do I need one?",
         "good": "A real-time OS guarantees bounded response times via priority-based preemptive scheduling, which matters when missing a deadline breaks the system (motor control, medical). Use one when you need deterministic latency, not just throughput. For simple, non-timing-critical firmware, a superloop may be enough and simpler.",
         "bad": "It is a real-time OS."},
        {"sub": "firmware", "type": "instruction", "tags": ["firmware", "security"],
         "user": "How do I secure firmware updates over the air?",
         "good": "Sign images with a private key and verify the signature on-device before applying; use a version/anti-rollback counter to block downgrade attacks; encrypt in transit and at rest if secrets are present. Apply atomically via A/B slots so a failed update can revert. Keep the updater in a protected boot stage.",
         "bad": "Sign the firmware."},
        {"sub": "gpu", "type": "qa", "tags": ["gpu", "nvlink"],
         "user": "What is NVLink and why use it instead of PCIe?",
         "good": "NVLink is NVIDIA's high-bandwidth, low-latency GPU-to-GPU interconnect, far faster than PCIe for multi-GPU training. It lets GPUs share memory and exchange gradients quickly, reducing communication bottlenecks in data-parallel training. PCIe is the general-purpose fallback; NVLink shines when GPUs must sync frequently.",
         "bad": "It connects GPUs faster."},
    ],
    "01_foundation": [
        {"sub": "general-reasoning", "type": "reasoning", "tags": ["arithmetic", "rate"],
         "user": "A train travels 60 km in 45 minutes. What is its average speed in km/h?",
         "good": "Convert time to hours: 45 min = 0.75 h. Speed = distance / time = 60 km / 0.75 h = 80 km/h. Average speed assumes constant-rate motion over the interval; real trips with stops would have a lower effective speed.",
         "bad": "80 km/h."},
        {"sub": "instruction-following", "type": "instruction", "tags": ["summarization"],
         "user": "Summarize this in exactly one sentence, preserving the main claim: 'The cache cut p99 latency from 340ms to 90ms but raised memory 18%.'",
         "good": "The new caching layer reduced p99 latency from 340ms to 90ms while increasing memory usage by 18%. A good one-sentence summary keeps the primary claim (latency drop) and the key caveat (memory cost) without adding interpretation.",
         "bad": "Latency improved."},
        {"sub": "problem-solving", "type": "reasoning", "tags": ["debugging", "tests"],
         "user": "How do I approach debugging a flaky test?",
         "good": "Reproduce it with the seed, retries, and parallelism isolated; capture logs and timing. Classify the cause: order dependence, shared state, async races, or resource contention. Add a targeted regression test that forces the condition, then fix the root cause rather than disabling or sleeping. Measure flake rate before/after.",
         "bad": "Re-run it until it passes."},
        {"sub": "communication", "type": "qa", "tags": ["communication", "stakeholders"],
         "user": "How do I explain technical debt to non-technical stakeholders?",
         "good": "Frame it as financial debt: a shortcut that speeds delivery now but accrues interest as slower changes and higher risk later. Quantify impact in their terms — delivery speed, bug rate, outage risk — and propose a paydown plan with a clear business trade-off rather than technical jargon.",
         "bad": "Compare it to a loan."},
        {"sub": "general-reasoning", "type": "reasoning", "tags": ["percentages", "arithmetic"],
         "user": "A shirt is 30% off and costs $70 after the discount. What was the original price?",
         "good": "If $70 is 70% of the original (100% - 30%), then original = 70 / 0.70 = $100. Check: 30% of $100 is $30 off, leaving $70. Working backward from the discounted price by dividing by the remaining fraction is the reliable method.",
         "bad": "About $100."},
        {"sub": "instruction-following", "type": "instruction", "tags": ["restructure"],
         "user": "Convert this paragraph into three bullet points: 'We shipped search, fixed login, and improved performance last sprint.'",
         "good": "· Shipped the new search feature.\n· Fixed the login bug.\n· Improved overall performance.\nInstruction-following means preserving every fact while changing only the format the user requested, with no added or dropped information.",
         "bad": "Make a list."},
        {"sub": "problem-solving", "type": "reasoning", "tags": ["prioritization"],
         "user": "How do I prioritize competing deadlines?",
         "good": "Rank by impact × urgency: what blocks others, what has external commitments, and what loses the most value if late. Negotiate scope or deadline on the lowest-impact item, and make trade-offs explicit to stakeholders. A simple impact/effort matrix prevents firefighting and documents the reasoning.",
         "bad": "Do the urgent ones first."},
        {"sub": "communication", "type": "instruction", "tags": ["writing", "status"],
         "user": "How do I write a clear project status update?",
         "good": "Lead with the current state (on track / at risk / blocked), then the top 3 items, owners, and dates. State risks and the ask explicitly. Keep it scannable with bullets and avoid surprise in the last line — surface bad news early so decisions can be made in time.",
         "bad": "List what you did."},
        {"sub": "general-reasoning", "type": "reasoning", "tags": ["rate", "latin-square"],
         "user": "If 5 machines make 5 widgets in 5 minutes, how long for 100 machines to make 100 widgets?",
         "good": "5 machines make 5 widgets in 5 minutes means each machine makes 1 widget in 5 minutes. With 100 machines working in parallel, they make 100 widgets in the same 5 minutes. The trick is per-machine rate, not total machines — parallelism preserves the per-unit time.",
         "bad": "5 minutes."},
        {"sub": "instruction-following", "type": "instruction", "tags": ["editing", "concise"],
         "user": "Rewrite this to be more concise without losing meaning: 'Due to the server being overloaded, it went down and users lost access.'",
         "good": "The overloaded server went down, so users lost access. Conciseness keeps the cause (overload), the event (went down), and the consequence (lost access) while dropping filler words like 'due to the fact that'.",
         "bad": "Server down, users out."},
        {"sub": "problem-solving", "type": "reasoning", "tags": ["estimation"],
         "user": "How do I estimate a project timeline I have never built before?",
         "good": "Break the work into smallest tasks, estimate each with a range (optimistic/realistic/pessimistic), and sum using a PERT-style weighted average. Add buffer for integration and unknowns, then validate against a spike on the riskiest part. Re-estimate after the first milestone as uncertainty drops.",
         "bad": "Guess and add buffer."},
        {"sub": "communication", "type": "qa", "tags": ["feedback", "communication"],
         "user": "How do I give constructive feedback to a colleague?",
         "good": "Be specific and timely: describe the observable behavior, its impact, and a concrete suggestion — not the person. Use 'when X happened, Y was the effect; consider Z' framing. Deliver privately, ask for their view, and agree on a next step. Balance critique with genuine recognition of what works.",
         "bad": "Be specific and kind."},
        {"sub": "general-reasoning", "type": "reasoning", "tags": ["exponential", "logic"],
         "user": "A pond's lily pads double daily and fill it on day 30. On what day was it half full?",
         "good": "Day 29. Because the pads double each day, the pond is half full the day before it is full. Working backward from the known endpoint (day 30 = full) is far more reliable than modeling forward, and it illustrates exponential growth's counterintuitive steepness.",
         "bad": "Day 29."},
    ],
}

# Distinct, valid-content records with NO metadata (tags/source/notes omitted).
# Used for the 'missing-metadata' bucket. Kept separate so their content never
# collides with the unique pool (avoiding accidental dedup).
META_EXAMPLES = [
    ("02_software_engineering", "debugging", "qa", "Why does my regex match too much text?",
     "Your pattern is greedy (.*) so it consumes everything to the last match. Use a lazy quantifier (.*?) or a negated class like [^<]* to stop at the first boundary."),
    ("02_software_engineering", "programming", "qa", "How do I sort a list of dicts by a key?",
     "Use `sorted(items, key=lambda d: d['name'])`. For reverse, pass `reverse=True`; for multiple keys return a tuple. This is stable, so equal keys keep their original order."),
    ("02_software_engineering", "algorithms", "reasoning", "When is a hash map the wrong choice?",
     "Avoid it when you need ordered traversal, range queries, or worst-case guarantees — a balanced BST gives those. Also skip it when keys lack a good hash or memory is tight, since hashing has overhead."),
    ("02_software_engineering", "software-architecture", "qa", "How do I handle backward-compatible API changes?",
     "Add new fields rather than renaming; keep old endpoints behind a version prefix; deprecate slowly with clear sunset dates. Use optional fields with defaults so old clients keep working."),
    ("02_software_engineering", "programming", "instruction", "How do I parse a CSV with quoted fields in Python?",
     "Use the stdlib `csv` module: `csv.reader` handles quotes and escapes correctly, unlike naive `split(','). Never split on commas manually when quoting is possible."),
    ("03_system_engineering", "linux", "qa", "How do I find what is listening on a port?",
     "Use `ss -ltnp 'sport = :8080'` (or `lsof -i :8080`). The `-p` shows the owning PID; run with privileges. For containers, run it inside the container too."),
    ("03_system_engineering", "docker", "qa", "What is a multi-stage Dockerfile?",
     "It uses multiple `FROM` stages; build dependencies in an early stage and copy only artifacts into a slim final stage, keeping the shipped image small and free of build tooling."),
    ("03_system_engineering", "networking", "reasoning", "What happens at TCP handshake?",
     "SYN, SYN-ACK, ACK: client and server exchange initial sequence numbers and options, establishing a reliable bidirectional channel before any data flows."),
    ("03_system_engineering", "kubernetes", "qa", "What is a ConfigMap used for?",
     "It stores non-secret configuration as key-value data mounted into pods as files or env vars, decoupling config from images so the same image runs in different environments."),
    ("03_system_engineering", "linux", "instruction", "How do I tail a log and filter for errors?",
     "Pipe `tail -f app.log | grep -i error` to stream only matching lines. For structured logs, use `jq` or `grep` on the level field. Combine with `tee` to also persist the filtered view."),
    ("04_ai_machine_learning", "llm", "qa", "What is a token in an LLM?",
     "A token is the unit of text the model reads/generates — a word piece or subword, not always a full word. Tokenization splits text into tokens the vocab indexes; counting tokens measures context length and cost."),
    ("04_ai_machine_learning", "rag", "reasoning", "Why might RAG return off-topic chunks?",
     "Often the embedding model misses domain vocabulary or chunking splits context. Fix with hybrid retrieval, domain-adapted embeddings, and a reranker; evaluate recall@k on labeled queries."),
    ("04_ai_machine_learning", "transformers", "qa", "What problem do transformers solve vs RNNs?",
     "They remove recurrence so training parallelizes across the sequence and long-range dependencies are captured directly by attention, instead of decaying through many RNN steps."),
    ("04_ai_machine_learning", "mlops", "instruction", "How do I track experiments?",
     "Log hyperparameters, metrics, code hash, and data version per run to a tracker (W&B/MLflow). Make runs comparable by fixing seeds and recording the exact environment for reproducibility."),
    ("04_ai_machine_learning", "llm", "qa", "What is prompt engineering?",
     "Designing the input text — instructions, context, examples — to steer model behavior without changing weights. Good prompts specify role, format, constraints, and provide few-shot exemplars."),
    ("05_hardware_engineering", "cpu", "qa", "What is a pipeline stall?",
     "A stall pauses the CPU pipeline when the next instruction cannot proceed — due to data dependency, cache miss, or branch mispredict — wasting cycles until the hazard clears."),
    ("05_hardware_engineering", "gpu", "reasoning", "Why use FP16 for training?",
     "FP16 halves memory and doubles throughput on tensor cores versus FP32, at some precision loss managed by loss scaling. It lets larger models and batches fit, speeding training."),
    ("05_hardware_engineering", "embedded-systems", "qa", "What is a watchdog timer?",
     "A hardware timer that resets the system if software fails to periodically 'kick' it, recovering from hangs. It is essential for unattended devices to self-heal."),
    ("05_hardware_engineering", "firmware", "instruction", "How do I make firmware fail-safe?",
     "Keep a known-good golden image, verify checksums before boot, and use A/B slots so a bad update reverts. Validate signatures and never erase the fallback until the new image boots."),
    ("05_hardware_engineering", "gpu", "qa", "What is VRAM and why is it limited?",
     "VRAM is the GPU's dedicated high-bandwidth memory holding weights, activations, and buffers. It is limited by die area, power, and cost, so it caps model size and batch."),
    ("01_foundation", "general-reasoning", "reasoning", "If 3 people paint a fence in 6 hours, how long for 6 people?",
     "Assuming linear parallelism, work is 18 person-hours, so 6 people take 3 hours. Real tasks have setup and coordination overhead, so the gain is rarely perfectly proportional."),
    ("01_foundation", "problem-solving", "qa", "How do I break a big task into steps?",
     "Decompose into the smallest shippable outcomes, order by dependency, and estimate each. Start with the riskiest piece to retire uncertainty early, then fill in the rest."),
    ("01_foundation", "communication", "instruction", "How do I write a clear email subject?",
     "State the action and topic in fewer than ten words, e.g. 'Review: Q3 launch plan (due Fri)'. A good subject lets the reader triage without opening the message."),
]


def content_hash(rec: dict) -> str:
    parts = [f"{m['role']}:{m['content'].strip().lower()}" for m in rec["messages"]]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def make_messages(system: str, user: str, assistant: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    ]


def main() -> int:
    random.seed(42)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []          # valid JSONL records (objects)
    malformed_lines: list[str] = []   # non-JSON lines
    exact_dup_hashes: list[str] = []
    near_dup_ids: list[str] = []
    missing_meta_ids: list[str] = []
    unique_ids: list[str] = []

    # --- 1. unique valid records (56): per-category quotas, mixed quality ---
    # Quotas sum to 56 so that 56 + 10 exact + 5 near + 23 missing + 5 invalid
    # + 1 malformed = exactly 100 raw lines, as the task requests.
    cat_order = list(EXAMPLES.keys())
    quotas = [12, 11, 11, 11, 11]
    cat_quota = dict(zip(cat_order, quotas))
    idx = 0
    good_unique_ids: list[str] = []  # long answers, reserved for near-dup bases
    for cat, ex_list in EXAMPLES.items():
        for j, ex in enumerate(ex_list[:cat_quota[cat]]):
            tier = idx % 3
            if tier == 0:
                ans = ex["good"]
                is_good = True
            elif tier == 1:
                # medium: truncate good answer at a word boundary (~180 chars)
                g = ex["good"]
                cut = g[:180].rsplit(" ", 1)[0]
                ans = cut + " (condensed)."
                is_good = False
            else:
                ans = ex["bad"]
                is_good = False
            sub = ex["sub"]
            rid = f"{cat}_{sub}_t{idx:04d}"
            rec = {
                "id": rid,
                "category": cat,
                "subcategory": sub,
                "type": ex["type"],
                "source": {
                    "name": "Atlas Synthetic Test",
                    "url": "tests/generate_synthetic_test.py",
                    "license": "CC-BY-4.0",
                    "date": "2026-07-27",
                },
                "messages": make_messages(SYSTEM_PROMPT, ex["user"], ans),
                "tags": ex["tags"],
                "quality_score": 0,
                "verified": False,
                "notes": f"synthetic unique {tier}-tier",
            }
            records.append(rec)
            unique_ids.append(rid)
            if is_good:
                good_unique_ids.append(rid)
            idx += 1

    # --- 2. exact duplicates (10): copy content of 10 unique records, new id ---
    dup_sources = unique_ids[:10]
    for k, rid in enumerate(dup_sources):
        src = next(r for r in records if r["id"] == rid)
        drec = json.loads(json.dumps(src))  # deep copy
        drec["id"] = f"{src['category']}_{src['subcategory']}_dup{k:03d}"
        drec["notes"] = "synthetic exact duplicate"
        records.append(drec)
        exact_dup_hashes.append(content_hash(drec))

    # --- 3. near duplicates (5): minimal variation of 5 LONG unique records ---
    # Bases MUST be the long (good) answers so the 4-gram Jaccard stays above
    # the 0.8 LSH threshold; appending a short clause to a short answer would
    # fall below threshold and not be detected.
    near_sources = good_unique_ids[:5]
    for k, rid in enumerate(near_sources):
        src = next(r for r in records if r["id"] == rid)
        nrec = json.loads(json.dumps(src))
        # append a short clarifying clause -> high Jaccard, but not exact
        last = nrec["messages"][-1]
        last["content"] = last["content"] + " (See the official docs for the canonical reference.)"
        nrec["id"] = f"{src['category']}_{src['subcategory']}_near{k:03d}"
        # stable content marker so the verifier can confirm the cluster was
        # collapsed regardless of which member the deduper keeps.
        nrec["notes"] = "synthetic near duplicate [NEAR-DUP-MARKER]"
        records.append(nrec)
        near_dup_ids.append(nrec["id"])

    # --- 4. missing-metadata records (23): valid content, no tags/source/notes ---
    for k, (cat, sub, rtype, user, ans) in enumerate(META_EXAMPLES):
        rid = f"{cat}_{sub}_meta{k:03d}"
        rec = {
            "category": cat,
            "subcategory": sub,
            "type": rtype,
            # intentionally omit: source, tags, notes (clean backfills them)
            # marker lets the verifier confirm the content survived backfilling.
            "messages": make_messages(SYSTEM_PROMPT, user, ans),
            "notes": "synthetic missing-metadata [META-MISSING-MARKER]",
            "quality_score": 0,
            "verified": False,
        }
        records.append(rec)
        missing_meta_ids.append(rid)

    # --- 5. invalid records (5 objects) + 1 malformed JSON line ---
    invalid_objects = [
        # empty messages
        {"id": "02_software_engineering_debugging_inv0001", "category": "02_software_engineering",
         "subcategory": "debugging", "type": "qa", "messages": []},
        # user only, no assistant
        {"id": "03_system_engineering_linux_inv0002", "category": "03_system_engineering",
         "subcategory": "linux", "type": "qa",
         "messages": [{"role": "user", "content": "What is the load average?"}]},
        # unknown category
        {"id": "99_unknown_cat_inv0003", "category": "99_unknown_cat",
         "subcategory": "x", "type": "qa",
         "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]},
        # missing category entirely
        {"id": "04_ai_machine_learning_llm_inv0004", "subcategory": "llm", "type": "qa",
         "messages": [{"role": "user", "content": "What is a token?"},
                      {"role": "assistant", "content": "A unit of text."}]},
        # message item missing content (clean drops: insufficient valid turns)
        {"id": "05_hardware_engineering_gpu_inv0005", "category": "05_hardware_engineering",
         "subcategory": "gpu", "type": "qa",
         "messages": [{"role": "user"}, {"role": "assistant", "content": "Bandwidth."}]},
    ]
    for rec in invalid_objects:
        records.append(rec)
    malformed_lines.append('{ this is not valid json, missing quotes and braces ')

    # --- shuffle deterministically so defects are interspersed ---
    random.shuffle(records)
    # interleave malformed lines at random positions
    all_lines = [json.dumps(r, ensure_ascii=False) for r in records]
    insert_at = random.sample(range(len(all_lines) + 1), len(malformed_lines))
    for pos, ml in zip(sorted(insert_at), malformed_lines):
        all_lines.insert(pos, ml)

    raw_path = OUT_DIR / "synthetic_test_v1.jsonl"
    raw_path.write_text("\n".join(all_lines) + "\n", encoding="utf-8")

    manifest = {
        "raw_path": str(raw_path),
        "friendly_to_canonical": FRIENDLY_TO_CANON,
        "raw_total_lines": len(all_lines),
        "invalid_object_count": len(invalid_objects),
        "malformed_line_count": len(malformed_lines),
        "exact_dup_hashes": exact_dup_hashes,
        "near_dup_ids": near_dup_ids,
        "missing_meta_ids": missing_meta_ids,
        "unique_ids": unique_ids,
        "expected_clean_kept": len(all_lines) - len(invalid_objects) - len(malformed_lines),
        "expected_dedup_dropped": len(exact_dup_hashes) + len(near_dup_ids),
        "expected_curated": len(all_lines) - len(invalid_objects) - len(malformed_lines)
                           - len(exact_dup_hashes) - len(near_dup_ids),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[gen] wrote {raw_path}")
    print(f"[gen] raw lines={len(all_lines)} "
          f"(unique={len(unique_ids)} exact_dups={len(exact_dup_hashes)} "
          f"near_dups={len(near_dup_ids)} missing_meta={len(missing_meta_ids)} "
          f"invalid_obj={len(invalid_objects)} malformed={len(malformed_lines)})")
    print(f"[gen] expected clean_kept={manifest['expected_clean_kept']} "
          f"dedup_dropped={manifest['expected_dedup_dropped']} "
          f"curated={manifest['expected_curated']}")
    print(f"[gen] manifest -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
