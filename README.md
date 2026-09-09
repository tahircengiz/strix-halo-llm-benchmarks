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

One flag matters more than the rest. `cache_prompt: false` is set on every run;
leave it on and the second pass over a prompt reports a cache hit rather than
your hardware.

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
