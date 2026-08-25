## Summary

<!-- What problem does this change solve? Keep the summary user-focused. -->

## Changes

-

## Validation

<!-- Include exact commands and relevant browser or integration evidence. -->

- [ ] `pnpm --filter web lint`
- [ ] `pnpm --filter web test`
- [ ] `pnpm --filter web build`
- [ ] `cd apps/api && uv run ruff check .`
- [ ] `cd apps/api && uv run ruff format --check .`
- [ ] `cd apps/api && uv run mypy app`
- [ ] `cd apps/api && uv run pytest`
- [ ] UI changes include fresh browser evidence and a clean console.
- [ ] Any skipped check is explained below.

Commands run:

```text
<!-- replace this comment with the commands and results -->
```

## Review checklist

- [ ] The change is focused and unrelated work is excluded.
- [ ] Public documentation is updated for setup, behavior, configuration, or
      security changes.
- [ ] API, schema, migration, and generated-file impacts are described.
- [ ] Contract changes start from `packages/contracts/*.schema.json`.
- [ ] No secrets, private data, raw DSPy reasoning, provider prompts, or
      unsanitized stack traces are included.
- [ ] UI changes include screenshots or equivalent browser evidence.
- [ ] I have read and will follow the [Code of Conduct](https://github.com/Qredence/fleet-agent/blob/main/CODE_OF_CONDUCT.md).
