# Raw measurements

`measurements.csv` is every campaign behind the figures in the top-level README.

One row per target per campaign. **Rows are only comparable inside a campaign** —
targets within one campaign were run interleaved (A, B, A, B) so that thermal
drift and background load landed on both sides equally. Comparing a number from
one campaign against a number from another is a weaker claim; the unchanged
production container appears in eleven of them and can be used to judge drift.

| Column | Meaning |
|---|---|
| `campaign` | UTC timestamp of the run; rows sharing one are interleaved |
| `decode_tok_s` | short-prompt generation rate, llama.cpp `predicted_per_second` |
| `prefill_tok_s` | 5.8k-token prompt, llama.cpp `prompt_per_second` |
| `ttft_s` | time to first token of any kind, measured client-side |
| `decode_1024_wall_s` | wall clock for a 1024-token generation |
| `concurrency2_s` | wall clock until two simultaneous requests both finish |
| `quality_set` | `v1` 19 items, `v2-hard` 14 items, `v1-draft` an early 12-item version |
| `empty_answer_items` | **read this before the score** |

## `empty_answer_items` is not a model failure

Two rows have a quality score that should be discarded:

| Campaign | Target | Score | Empty answers |
|---|---|---:|---:|
| `20260917T162240Z` | `B-qwen36-mtpoff` | 5/19 | 15 |
| `20260917T180122Z` | `D1-ling3-think` | 17/19 | 2 |

Both are reasoning models that spent the whole token budget in
`reasoning_content` and returned empty `content`. The harness counted that as a
wrong answer. It is a measurement bug, not a model result — the same model
scored 16/19 once the budget was raised and thinking was disabled. The column
is kept rather than the rows deleted, because the failure mode is worth
knowing about if you are building your own harness.

`ttft_s` is blank for quality-only campaigns, which skip the timing categories.
