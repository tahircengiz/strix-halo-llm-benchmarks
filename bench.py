#!/usr/bin/env python3
"""Sweep a llama.cpp server across prompt sizes and print what it reports.

Numbers come from llama.cpp's own `timings` block rather than a wall clock on
this side, so the server is the one making the claim. Nothing is installed:
Python's standard library is enough.

    ./bench.py --url http://localhost:8084

Prompt sizes are reached by repeating one fixed sentence, which keeps token
counts exact instead of estimated. `cache_prompt` is off for every run; leave
it on and the second run of a prompt reports a prefill speed that describes a
cache hit rather than your hardware.
"""

import argparse
import json
import urllib.request

SENTENCE = "The quick brown fox jumps over the lazy dog. "
TOKENS_PER_REP = 10  # measured for this sentence; the server reports the truth


def run(url: str, reps: int, n_predict: int) -> dict:
    body = json.dumps(
        {
            "prompt": SENTENCE * reps if reps else "Explain what a KV cache is.",
            "n_predict": n_predict,
            "temperature": 0,
            "cache_prompt": False,
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/completion", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=1800) as r:
        return json.load(r)["timings"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8084")
    ap.add_argument("--n-predict", type=int, default=128)
    ap.add_argument(
        "--reps",
        type=int,
        nargs="+",
        default=[0, 1200, 2400, 4800],
        help="sentence repetitions per run; 0 is a short prompt",
    )
    a = ap.parse_args()

    print(f"{'prompt tokens':>14}  {'prefill':>12}  {'decode':>12}  {'prefill time':>13}")
    print("-" * 58)
    for reps in a.reps:
        t = run(a.url, reps, a.n_predict)
        print(
            f"{t['prompt_n']:>14,}  {t['prompt_per_second']:>8.1f} tok/s"
            f"  {t['predicted_per_second']:>8.2f} tok/s  {t['prompt_ms'] / 1000:>10.2f} s"
        )


if __name__ == "__main__":
    main()
