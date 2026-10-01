# Training and evaluation configs

Model-family matrices for the **Prime Intellect** CLI. These files are not
read by Fleet Agent itself; each one is a config for an external command:

| Directory | Command | Purpose |
|---|---|---|
| `configs/eval/` | `prime eval run <file>.toml` | Baseline model evaluations |
| `configs/gepa/` | `prime gepa run <file>.toml` | GEPA prompt optimization |
| `configs/rl/` | `prime train <file>.toml` | Hosted Training (RL) runs |

Hosted Training docs: https://docs.primeintellect.ai/hosted-training

## Conventions

- One file per model family; the commented lines above `model` are a size
  menu — uncomment exactly one (GEPA files carry a matching
  `reflection_model` that must be switched together).
- The active `[[eval]]` / `[[env]]` block picks the environment
  (`primeintellect/reverse-text` by default); the commented blocks are the
  other options.
- The key names differ by directory **on purpose**: each file mirrors the
  config schema of its own command (`[[eval]] env_id` for `prime eval`,
  `[[env]] env_id` for `prime gepa`, `[[env]] id` for `prime train`). Do not
  "normalize" them across directories — TOML has no include mechanism, and
  the tools read these keys as-is.

## Not to be confused with

- `apps/api/evals/` — Fleet Agent's own offline DSPy evaluation/optimization
  harness (deterministic scorers, MLflow tracking). See `docs/dspy-agent.md`.
- `apps/api/.env` — the API server's runtime configuration (see
  `apps/api/.env.example`).
