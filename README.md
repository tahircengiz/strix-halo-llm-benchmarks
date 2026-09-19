# Strix Halo, measured

Notes from running local LLM inference on a **Ryzen AI MAX+ 395** box every day:
a Beelink GTR9 Pro with 128 GB of LPDDR5X, 96 GiB of it handed to the integrated
Radeon 8060S.

There is a lot written about what this hardware *could* do. This is what it
actually does, measured on the machine, with the commands to reproduce every
number. Where something surprised me, I say so. Where I have not measured
something, I say that too.

## The short version

| | |
|---|---|
| The runtime that ships | Vulkan, not ROCm, even with ROCm 7.2.1 installed |
| The identity trap | `rocminfo` reports `gfx1150`, the Vulkan driver reports `GFX1151` |
| What 128 GB buys you | 96 GiB to the iGPU, 31 GiB to the OS, and no swap |
| Decode speed, short prompt | 88 tok/s on a 30B MoE at Q4_K_M |
| Decode speed, 48k prompt | 30 tok/s, a 66% fall |
| Prefill time, 48k prompt | **3 minutes 9 seconds** |
| The real constraint | Not memory. Prefill. |
| The backend trade | ROCm is **+28% prefill**, Vulkan is **+13% decode**, quality identical |
| Picking a model | Expert count matters more than parameter count: 128 experts beat 256 by 33% |

## Vulkan, not ROCm

ROCm 7.2.1 is installed on this box. Every inference container in production
runs the **Vulkan** build anyway:

```
ghcr.io/ggml-org/llama.cpp:server-vulkan
ghcr.io/ggml-org/whisper.cpp:main-vulkan
```

This was not a principled decision at first. Ollama picked Vulkan on its own
and logged `library=Vulkan` instead of the ROCm path I expected. Rather than
fight it, I measured it, found the performance acceptable, and stopped fighting
it everywhere else too.

If you are setting this hardware up, the useful advice is to try Vulkan first.
It is one image pull, it needs no `HSA_OVERRIDE_GFX_VERSION` guesswork, and on
this chip it is what I would have ended up with anyway.

### Then I actually measured ROCm

The paragraph above was an admission, not a finding: Vulkan shipped because it
worked, not because it won anything. So I ran both.

Same model file, same flags, same 49,152 tokens per slot, and — this part
matters — **the same llama.cpp build on both sides**. The ROCm image ships at a
different build number than the Vulkan one I had been running, so comparing
them directly would have measured a version bump as well as a backend. I pulled
the current Vulkan image by digest and ran the production build as a third
target to separate the two.

| | Vulkan | ROCm/HIP | |
|---|---:|---:|---|
| Decode, short prompt | **87.5 tok/s** | 77.2 tok/s | Vulkan +13.3% |
| Prefill, 5.8k prompt | 1,187 tok/s | **1,516 tok/s** | ROCm +27.7% |
| Time to first token, 5.8k | 5.05 s | **3.87 s** | ROCm −23.4% |
| Quality, 19-item set | 18/19 | 18/19 | identical |

Vulkan wins the steady-state decode rate. ROCm wins prefill — and this repo's
whole argument is that **prefill is the constraint**, so that is the column that
should decide, not the one I had been watching.

There is a sharper version of the same result. Send a 5.8k-token request, then
send a short one to the same server:

| | Vulkan | ROCm |
|---|---:|---:|
| TTFT, fresh slot | 0.240 s | **0.082 s** |
| TTFT, right after a 5.8k request | 2.879 s | **0.209 s** |

Fourteen times. Three runs, same result each time. A chat server takes long
RAG-shaped requests and short follow-ups on the same slots all day, so this is
not a synthetic case.

What I would tell someone setting this up now: run Vulkan if your load is
long-form generation, run ROCm if it is retrieval, summarisation, or anything
that feeds the model a large prompt for a short answer. Neither is the default
answer. If you do run ROCm, check that `GGML_HIP_ROCWMMA_FATTN` is **off** —
[llama.cpp#24437](https://github.com/ggml-org/llama.cpp/issues/24437) reports a
prefill regression of up to 41% at long context on gfx1151 when it is on.

One more result that saved me a job: upgrading llama.cpp from build 10615 to
11011 changed decode by −2.1% and prefill by +0.6%. On this chip, a newer
llama.cpp is not a performance upgrade. Upgrade for architecture support, not
for speed.

## `rocminfo` says gfx1150, the Vulkan driver says GFX1151

Both, on the same machine, at the same time:

```console
$ rocminfo | grep -E 'gfx11|Marketing Name'
  Marketing Name:          AMD RYZEN AI MAX+ 395 w/ Radeon 8060S
  Name:                    gfx1150
  Marketing Name:          Radeon 8060S Graphics
      Name:                    amdgcn-amd-amdhsa--gfx1150
      Name:                    amdgcn-amd-amdhsa--gfx11-generic

$ vulkaninfo --summary | grep -E 'deviceName|driverName'
	deviceName         = Radeon 8060S Graphics (RADV GFX1151)
	driverName         = radv
```

The architecture is gfx1151. ROCm naming it `gfx1150` matters because libraries
that select a kernel by target string can pick the wrong one, which is where
`HSA_OVERRIDE_GFX_VERSION` advice comes from. On the Vulkan path the question
does not arise, which is a second reason it is the easier road.

## 128 GB of unified memory is not 128 GB

The number on the box is 128 GB. What you get is a split, fixed in firmware:

```console
$ rocm-smi --showmeminfo vram
GPU[0]		: VRAM Total Memory (B): 103079215104     # 96 GiB

$ free -b | awk '/Mem:/{printf "%.1f GiB\n", $2/1073741824}'
31.0 GiB

$ swapon --show
                                                  # nothing. no swap.
```

96 GiB for models, 31 GiB for everything else, and no swap to fall back on. The
consequence is not subtle: a large Docker build, a JVM, or a database restore
will meet the OOM killer on a machine advertising 128 GB. Size the host side of
your workload against 31 GiB, not 128.

## The setup

Everything above and below was measured on this, and nowhere else.

**Hardware.** Beelink GTR Pro, BIOS `GTRP108`. AMD Ryzen AI MAX+ 395, 16 cores
and 32 threads, integrated Radeon 8060S with 40 compute units. Eight LPDDR5
modules of 16 GB each, 128 GB total, running at 8000 MT/s. That memory speed is
the number to keep in mind for every result here.

**Firmware.** The iGPU allocation is a BIOS setting, not a runtime one. UMA /
iGPU VRAM is set to 96 GB, which the driver then reports as `VRAM: 98304M`.
Worth knowing before you flash anything: programming NVRAM during a BIOS update
resets this to the default, and a low allocation makes large models fail in
ways that look like software problems.

**Kernel.** Ubuntu 24.04.4 LTS on `6.17.0-1032-oem`, with these parameters,
which took some finding:

```
amdgpu.gttsize=49152 ttm.pages_limit=12288000 pcie_aspm=off
```

**Userspace.** Mesa 25.2.8 (RADV), ROCm 7.2.1 installed but unused by the
inference path, Docker 29.7.2.

**The engine.** llama.cpp server, Vulkan build, revision
`f280b26983ad0fdb705a0d9ebf0503e76f2899b0`, reported by the binary as
`b10615-f280b2698`:

```
ghcr.io/ggml-org/llama.cpp@sha256:8546a30401a6c7ec573e22b16193ff3fb58af2a0329ed4f48e432340075ce943
```

Run as:

```bash
docker run -d --name qwen30b-llamacpp \
  --device /dev/dri \
  -v /path/to/models:/models \
  -p 8084:8080 \
  --memory 6g \
  --restart unless-stopped \
  ghcr.io/ggml-org/llama.cpp:server-vulkan \
    -m /models/Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf \
    -a qwen3-30b-a3b-gguf --host 0.0.0.0 --port 8080 \
    -ngl 99 -c 98304 -np 2 -cram 2048 --jinja --metrics
```

Only `/dev/dri` is passed in. The Vulkan path needs no ROCm device nodes, no
`HSA_OVERRIDE_GFX_VERSION`, and no privileged container. The 6 GB memory limit
is a host-RAM limit and does not touch VRAM; it exists because this box has
31 GiB of system memory and no swap.

**The model.** `Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf`, 18 GB on disk.

**Method.** Temperature 0, `cache_prompt: false`, 128 tokens generated per run,
numbers taken from llama.cpp's own `timings` block in the response. Prompts were
built by repeating a fixed sentence, so token counts are exact rather than
estimated.

**What else was running.** This is a working machine, not a clean bench, and the
results are honest about that. Three other models were resident in VRAM
throughout:

| container | model |
|---|---|
| `qwen3-embed` | Qwen3-Embedding-0.6B, f16 |
| `qwen3-rerank` | Qwen3-Reranker-0.6B, q8_0 |
| `whisper-stt` | whisper large-v3-turbo |

Total VRAM in use was 32.7 GiB of 96 GiB, so there was no memory pressure, but
the GPU was not exclusively mine. None of the three served a request during the
runs. A dedicated box would likely do slightly better than the figures below;
it would not change their shape.

## The numbers

| Prompt tokens | Prefill | Decode | Prefill time |
|---:|---:|---:|---:|
| 11 | 122 tok/s | 88.40 tok/s | 0.09 s |
| 12,001 | 920 tok/s | 58.57 tok/s | 13.0 s |
| 24,001 | 549 tok/s | 44.47 tok/s | 43.8 s |
| 48,001 | 254 tok/s | 30.06 tok/s | **189.0 s** |

The last column is llama.cpp's `prompt_ms`, the time spent processing the
prompt. Time to first token is that plus a single decode step, so at these
sizes the two are the same number to the eye.

Two runs of the short prompt returned 88.40 and 88.41 tok/s, so the decode
figures are stable rather than lucky.

Read the prefill column twice. It peaks at 12k and then **falls**, from 920
tok/s to 254 tok/s by 48k. Attention cost grows faster than the batch
efficiency you gain, and the curve bends the wrong way exactly where a large
context window was supposed to be the selling point.

## What the numbers mean for context length

The server runs with `-c 98304 -np 2`. That reads like a 98k context window.
It is not, per request:

```console
$ curl -s localhost:8084/props | python3 -c 'import json,sys; print(json.load(sys.stdin)["default_generation_settings"]["n_ctx"])'
49152
```

`-np 2` divides the context between two slots, so a single request gets 49,152
tokens. That makes the 48k row above the practical ceiling for one prompt, not
a point on the way to something larger.

And at that ceiling the first token costs **three minutes**. The 96 GiB of VRAM
genuinely lets you allocate the KV cache for a context this size. Nothing about
the memory stops you. The bandwidth and the attention arithmetic do. If you are
buying this hardware for long-context work, budget by prefill time, not by how
much cache fits.

## Why a MoE model is the right choice here

88 tok/s of decode from a 30B model on integrated graphics looks wrong until
you notice the `A3B` in the name. Qwen3-30B-A3B is a mixture of experts with
roughly 3B parameters active per token. Decode is bandwidth-bound on the
parameters it actually touches, and LPDDR5X is the weak link in this design.

So the two halves of the hardware want different things, and a MoE satisfies
both. The 96 GiB is what lets you *hold* a 30B model with a large cache. The
3B active footprint is what makes each token cheap enough to be pleasant. A
dense 30B on this chip would be held just as comfortably and would decode at a
fraction of the speed.

### Active parameters set a ceiling, not a ranking

That is where I stopped for a while, and it was not enough. I measured four MoE
models whose active parameter counts are all within half a billion of each
other, expecting them to land in the same place. They did not:

| Model | Experts → active | Quant | Decode |
|---|---|---|---:|
| gpt-oss-20b | 32 → 4 | MXFP4 | 77.1 tok/s |
| **Qwen3-30B-A3B** | **128 → 8** | **Q4_K_M** | **88.7 tok/s** |
| Qwen3.6-35B-A3B | 256 → 8 | Q4_K_XL | 59.2 tok/s |
| Ling-3.0-flash | 512 → 8+1 | Q3_K_M | 49.2 tok/s |

Same active footprint, 49 to 89 tok/s. The variable that tracks is the number
of experts to choose from. More experts means the weights you touch are
scattered more thinly across memory, and the router has more work to do before
any of them are read. On a chip whose limit is memory bandwidth, that shows up
directly in the decode rate.

The 256-expert row is the honest one. I first measured that model at `UD-Q6_K`
and it came in 37% behind — but the quant was heavier too, so the comparison
proved nothing. Re-running it at `UD-Q4_K_XL`, matched to the incumbent's quant
class, moved it only to −33%. Four points were the quant. The rest is the
architecture.

If you are picking a model for this hardware, read the expert count before the
parameter count.

### Smaller files are not automatically faster

The same instinct that makes active parameters look decisive makes low-bit
quants look decisive, and it fails the same way.

| Quant | File | Decode |
|---|---:|---:|
| Q3_K_M (Ling) | 62.6 GB | 49.2 tok/s |
| Q4_K_M | 18.6 GB | 88.6 tok/s |
| UD-Q4_K_XL | 17.7 GB | **89.8 tok/s** |
| UD-Q6_K (Qwen3.6) | 30.0 GB | 56.2 tok/s |

Q3 reads fewer bytes per token than Q4 and is slower anyway: the unpacking cost
on the Vulkan side eats the saving. Q6 costs what you would expect. The Q4_K
family is the sweet spot on this chip, and within it the Unsloth dynamic quant
was 1.4% faster than plain `Q4_K_M` at a file 0.87 GB smaller, with an
identical score on both of my quality sets.

I also tried the other end of the scale. A ternary (2.13 bpw) build of a dense
27B ran at 53 tok/s on a 4070 Ti — the quantisation does what it claims, it
makes a dense model viable. It does not beat sparsity here: that model reads
7.2 GB of weights per token, where the A3B reads about 1.8 GB.

That is the buying guidance in one line: this machine is for models that are
large at rest and small in motion.

## What does not work

There is no CUDA here, and no amount of configuration changes that. Anything
built against it is simply unavailable: TensorRT, NVIDIA Dynamo, most NVENC
tooling, and any project whose install instructions begin with a CUDA wheel.
Plan for the Vulkan or ROCm branch of a project to exist before you rely on it.

## The NPU is there and I do not use it

`rocminfo` lists a second accelerator:

```
  Marketing Name:          RyzenAI-npu5
```

It is real, it is idle, and nothing in my inference stack targets it. I am not
going to pretend otherwise. If you are counting on the NPU for LLM work today,
verify that your engine supports it before you buy.

## Reproducing this

The harness is in this repository. It needs nothing installed beyond Python's
standard library, and it can be run from any machine that can reach the server:

```bash
./bench.py --url http://localhost:8084
```

Every figure comes from llama.cpp's own `timings` block, which is the least
arguable source available: ask the server and print what it reports, rather
than timing it from the outside and hoping the network was quiet.

A second sweep on a later run returned 917.6 tok/s prefill and 58.20 tok/s
decode at 12k, against 919.9 and 58.57 the first time. That is agreement inside
half a percent, which is the only reason I am comfortable publishing figures to
two decimal places.

The later comparison work gave a longer version of the same check. Across
**eleven independent campaigns** spread over three days, each one re-measuring
the unchanged production container alongside whatever was being tested that
day, short-prompt decode came in at a median of **88.61 tok/s**, range
87.22–89.49, a spread of 2.6%. Within any single campaign the spread was
usually 0.1–0.3%. Every comparison in this README that pits one thing against
another was run interleaved — A, B, A, B — so that thermal drift and whatever
else the box was doing landed on both sides equally.

Two measurement traps cost me real numbers before I caught them, and both are
easy to hit:

- **Prompt cache.** Repeat an identical prefill prompt and the second run
  reports `prompt_n: 1` and a speed that describes a cache hit. It turned
  1,196 tok/s into 56 tok/s in one of my runs. `cache_prompt: false` handles it
  here; if your harness cannot set that, vary the prompt per repetition.
- **Reasoning models.** If the model emits thinking tokens, llama.cpp puts them
  in `reasoning_content` and leaves `content` empty until it is done. Count only
  `content` and a reasoning model looks like it produced nothing for twenty
  seconds. Worse, a token budget sized for a non-reasoning model gets spent
  entirely on thinking, and the model scores zero on questions it can answer.

One flag matters more than the rest. `cache_prompt: false` is set on every run;
leave it on and the second pass over a prompt reports a cache hit rather than
your hardware.

Every campaign behind the comparison tables is in
[`results/measurements.csv`](results/measurements.csv), one row per target per
run, including two rows whose quality score is a harness artefact rather than a
model result. `results/README.md` says which and why.

For sweeping an endpoint more broadly than prompt length, I use
[LLM-Inference-Toolkit](https://github.com/tahircengiz/LLM-Inference-Toolkit),
which also installs nothing. To work out whether a model and context will fit
before downloading 18 GB of weights, there is
[LLMScale](https://tahircengiz.github.io/LLMScale/).

## Licence

[CC BY 4.0](LICENSE). Use the numbers, quote the findings, reuse the harness.
The one condition is attribution, which for measurements is the point: a figure
is only worth anything if a reader can trace it back to the machine, the build
and the method that produced it.

## Corrections welcome

If your Strix Halo behaves differently, I want to know. Open an issue with
your engine, build, model, quantisation and the raw `timings` block, and I
will add it here.

---

Measured 9 September 2026. ROCm 7.2.1, Mesa RADV, llama.cpp `b10615-f280b2698`.
