"""
QC Intel — Open-Source LLM Judge for Product Match Validation

Runs on Kaggle T4 GPU. Replaces Gemini API match validation (~$1/run) with
Qwen2.5-7B-Instruct in int8 quantization.

Task: Binary classification — "Are these the same product?" on ambiguous pairs
(0.80–0.85 embedding similarity).

Modes:
  1. Benchmark: Compare open-source LLM answers against Gemini ground truth.
     Reports accuracy, precision, recall, F1. Pass threshold: >= 95% accuracy.
  2. Production: Judge all ambiguous pairs, output verdicts.

Input:  /kaggle/input/qc-intel-judge-pairs/pairs.json
Output: judge_results.json, benchmark_results.json (if ground truth present)
"""

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_KAGGLE_PATHS = [
    Path("/kaggle/input/datasets/manmohanbuilds/qc-intel-judge-pairs"),
    Path("/kaggle/input/qc-intel-judge-pairs"),
]
INPUT_DIR = Path("input")  # fallback
for _p in _KAGGLE_PATHS:
    if _p.exists():
        INPUT_DIR = _p
        break

PAIRS_PATH = INPUT_DIR / "pairs.json"
RESULTS_OUT = Path("judge_results.json")
BENCHMARK_OUT = Path("benchmark_results.json")

# Model config
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
MODELS_DIR = Path("/kaggle/input/datasets/manmohanbuilds/qc-intel-llm-models")
if not MODELS_DIR.exists():
    MODELS_DIR = Path("/kaggle/input/qc-intel-llm-models")

LOCAL_MODEL_PATH = MODELS_DIR / "Qwen2.5-7B-Instruct"

# Force offline if model is pre-uploaded
if LOCAL_MODEL_PATH.exists():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

PROMPT_TEMPLATE = """You are a product matching expert for Indian quick commerce platforms (Blinkit, Zepto, Instamart).

Determine if these two product listings refer to the SAME physical product (same brand, same variant, same size/weight).

Product A: {name_a} ({brand_a}, {unit_a})
Product B: {name_b} ({brand_b}, {unit_b})
Embedding similarity: {similarity:.2f}

Rules:
- Same brand + same variant + same size = YES
- Different brand = NO
- Same brand but different variant (e.g. "Toned" vs "Full Cream") = NO
- Same brand but different size (e.g. "500ml" vs "1L") = NO
- Minor name differences across platforms (e.g. "Amul Taaza" vs "Amul Taaza Toned Milk") = YES if same product

Answer with ONLY "YES" or "NO"."""


def load_model() -> tuple[Any, Any]:
    """Load Qwen2.5-7B-Instruct with int8 quantization."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    model_path = str(LOCAL_MODEL_PATH) if LOCAL_MODEL_PATH.exists() else MODEL_NAME
    log.info("Loading model from: %s", model_path)

    quantization_config = BitsAndBytesConfig(
        load_in_8bit=True,
        llm_int8_threshold=6.0,
    )

    tokenizer = AutoTokenizer.from_pretrained(
        model_path,
        trust_remote_code=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        quantization_config=quantization_config,
        device_map="auto",
        trust_remote_code=True,
        torch_dtype=torch.float16,
    )

    log.info("Model loaded. Device map: %s", getattr(model, "hf_device_map", "n/a"))
    return model, tokenizer


def judge_pair(
    model: Any,
    tokenizer: Any,
    pair: dict[str, Any],
) -> str:
    """Run inference on a single pair. Returns 'YES' or 'NO'."""
    import torch

    prompt = PROMPT_TEMPLATE.format(
        name_a=pair["name_a"],
        brand_a=pair["brand_a"],
        unit_a=pair["unit_a"],
        name_b=pair["name_b"],
        brand_b=pair["brand_b"],
        unit_b=pair["unit_b"],
        similarity=pair["similarity"],
    )

    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=5,
            do_sample=False,
            temperature=1.0,
            pad_token_id=tokenizer.eos_token_id,
        )

    # Decode only the generated tokens (skip prompt)
    generated = outputs[0][inputs["input_ids"].shape[1]:]
    answer = tokenizer.decode(generated, skip_special_tokens=True).strip().upper()

    # Normalize to YES/NO
    if answer.startswith("YES"):
        return "YES"
    return "NO"


def judge_batch(
    model: Any,
    tokenizer: Any,
    pairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Judge all pairs and return results with verdicts."""
    results = []
    for i, pair in enumerate(pairs):
        t0 = time.time()
        verdict = judge_pair(model, tokenizer, pair)
        elapsed = time.time() - t0

        result = {
            "pair_id": pair.get("pair_id", i),
            "catalog_id_a": pair.get("catalog_id_a"),
            "catalog_id_b": pair.get("catalog_id_b"),
            "name_a": pair["name_a"],
            "name_b": pair["name_b"],
            "similarity": pair["similarity"],
            "verdict": verdict,
            "inference_time_s": round(elapsed, 3),
        }
        results.append(result)

        if (i + 1) % 10 == 0 or i == len(pairs) - 1:
            log.info("Judged %d/%d pairs (last: %s in %.2fs)", i + 1, len(pairs), verdict, elapsed)

    return results


def run_benchmark(
    results: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare LLM verdicts against Gemini ground truth. Returns metrics."""
    # Ground truth must be present in pairs
    pairs_with_gt = [p for p in pairs if "gemini_verdict" in p]
    if not pairs_with_gt:
        log.info("No Gemini ground truth found — skipping benchmark")
        return {}

    gt_by_id = {p.get("pair_id", i): p["gemini_verdict"].upper().startswith("YES") for i, p in enumerate(pairs_with_gt)}
    results_by_id = {r["pair_id"]: r["verdict"] == "YES" for r in results}

    tp = fp = tn = fn = 0
    mismatches = []

    for pair_id, gt_yes in gt_by_id.items():
        if pair_id not in results_by_id:
            continue
        pred_yes = results_by_id[pair_id]

        if gt_yes and pred_yes:
            tp += 1
        elif gt_yes and not pred_yes:
            fn += 1
            mismatches.append({"pair_id": pair_id, "type": "false_negative"})
        elif not gt_yes and pred_yes:
            fp += 1
            mismatches.append({"pair_id": pair_id, "type": "false_positive"})
        else:
            tn += 1

    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    benchmark = {
        "total_pairs": total,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "pass_threshold": 0.95,
        "passed": accuracy >= 0.95,
        "mismatches": mismatches[:20],  # Cap for output size
    }

    log.info("Benchmark: accuracy=%.2f%% (threshold=95%%) — %s",
             accuracy * 100, "PASSED" if benchmark["passed"] else "FAILED")
    log.info("  TP=%d FP=%d TN=%d FN=%d", tp, fp, tn, fn)

    return benchmark


def main() -> None:
    log.info("QC Intel — LLM Judge (Qwen2.5-7B-Instruct int8)")
    log.info("GPU available: %s", os.environ.get("CUDA_VISIBLE_DEVICES", "not set"))

    # Detect GPU
    try:
        import torch
        log.info("PyTorch CUDA: %s (devices: %d)", torch.cuda.is_available(), torch.cuda.device_count())
        if torch.cuda.is_available():
            log.info("GPU: %s", torch.cuda.get_device_name(0))
    except ImportError:
        log.warning("PyTorch not available")

    # Debug: list input
    kaggle_input = Path("/kaggle/input")
    if kaggle_input.exists():
        log.info("Contents of /kaggle/input/: %s", list(kaggle_input.iterdir()))

    log.info("INPUT_DIR: %s (exists=%s)", INPUT_DIR, INPUT_DIR.exists())
    log.info("PAIRS_PATH: %s (exists=%s)", PAIRS_PATH, PAIRS_PATH.exists())

    if not PAIRS_PATH.exists():
        log.error("Pairs file not found at %s", PAIRS_PATH)
        return

    # Load pairs
    with open(PAIRS_PATH) as f:
        data = json.load(f)

    pairs = data.get("pairs", data) if isinstance(data, dict) else data
    log.info("Loaded %d pairs to judge", len(pairs))

    if not pairs:
        log.info("No pairs to judge — exiting")
        # Write empty results
        with open(RESULTS_OUT, "w") as f:
            json.dump({"verdicts": [], "model": MODEL_NAME, "count": 0}, f)
        return

    # Load model
    total_start = time.time()
    model, tokenizer = load_model()
    load_time = time.time() - total_start
    log.info("Model loaded in %.1fs", load_time)

    # Judge all pairs
    t0 = time.time()
    results = judge_batch(model, tokenizer, pairs)
    judge_time = time.time() - t0
    log.info("Judged %d pairs in %.1fs (%.2f s/pair)", len(results), judge_time, judge_time / len(results))

    # Write results
    output = {
        "model": MODEL_NAME,
        "quantization": "int8",
        "timestamp": datetime.now(UTC).isoformat(),
        "count": len(results),
        "model_load_time_s": round(load_time, 1),
        "total_judge_time_s": round(judge_time, 1),
        "avg_time_per_pair_s": round(judge_time / len(results), 3) if results else 0,
        "verdicts": results,
    }

    yes_count = sum(1 for r in results if r["verdict"] == "YES")
    log.info("Verdicts: %d YES, %d NO (%.1f%% match rate)",
             yes_count, len(results) - yes_count, yes_count / len(results) * 100 if results else 0)

    with open(RESULTS_OUT, "w") as f:
        json.dump(output, f, indent=2)
    log.info("Results written to %s", RESULTS_OUT)

    # Benchmark against Gemini ground truth if available
    benchmark = run_benchmark(results, pairs)
    if benchmark:
        with open(BENCHMARK_OUT, "w") as f:
            json.dump(benchmark, f, indent=2)
        log.info("Benchmark written to %s", BENCHMARK_OUT)

    total_elapsed = time.time() - total_start
    log.info("Total runtime: %.1fs (%.1f min)", total_elapsed, total_elapsed / 60)


if __name__ == "__main__":
    main()
