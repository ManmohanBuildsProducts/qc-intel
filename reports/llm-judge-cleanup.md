# LLM Judge Cleanup Report

**Date:** 2026-03-29
**DB:** `data/qc_intel.db`
**Command:** `python eval/eval_normalization.py --llm-judge --fix`

## Summary

| Metric | Value |
|--------|-------|
| Ambiguous pairs evaluated (sim 0.70–0.85) | 126 |
| Verified correct by Gemini | 35 (27.8%) |
| Rejected as bad matches | 91 (72.2%) |
| Bad mappings deleted from DB | 91 |

## Action Taken

All 91 rejected mappings were deleted from `product_mappings` table via `--fix` flag.

## Sample Rejected Matches

| Sim | Product A | Product B |
|-----|-----------|-----------|
| 0.850 | Amul Amul Taaza Toned Milk (200 ml) | Amul Taaza Tetra (200 ml) |
| 0.850 | Yellow Diamond Sizzling Cheese Potato Chips (85 g) | YELLOW DIAMOND Sizzling Cheese Chips (85 g) |
| 0.849 | Brooke Bond Taaza Tea (1 kg) | Taaza Tea (1 kg) |
| 0.848 | Norang Flour Mills Chakki Fresh Whole Wheat Atta (5 kg) | Sunpure Swaad Chakki Atta (5 kg) |
| 0.848 | Tata Tea Agni Special Blend Tea (250 g) | Tata Tea Agni Dust Black Tea (250 g) |
| ... | +86 more rejected pairs | |

## Observations

- The ambiguous zone (0.70–0.85 cosine similarity) had a 72.2% false positive rate, confirming that embedding similarity alone is unreliable in this range.
- Many rejected pairs were same-brand products with different variants (e.g., "Taaza Toned Milk" vs "Taaza Tetra"), or same-category products from different brands that share keywords.
- The 35 verified pairs represent legitimate cross-platform matches where naming differs but the product is the same.

## Next Steps

- Consider raising the ambiguous lower threshold above 0.70 to reduce the volume of pairs needing LLM validation.
- Re-run `--fast` (Strategy 3 rule-based checks) to verify reduced noise after cleanup.
