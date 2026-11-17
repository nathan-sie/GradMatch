# H2 candidate runner

This CLI is an ungraded development interface on `homework/eval-harness-50`. It uses the H1 frozen experiment and snapshot evidence, independently of the public SQLite file and deployed app. It does not execute the 50-task homework evaluation.

## One task

Run from the repository root with Python 3.12 and the installed project dependencies:

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.run_task --strategy react --task-id d01
.\.venv\Scripts\python.exe -m scripts.homework.run_task --strategy fixed --task-id d08
```

These defaults make no model requests, even when a key is configured. A `model_disabled` outcome is saved and the command returns exit code 1. It does not simulate a model answer. For real calls, the existing local configuration must have an API key and `MODEL_ENABLED=true`, and the command must include `--live-model`:

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.run_task --strategy react --task-id d01 --live-model
.\.venv\Scripts\python.exe -m scripts.homework.run_task --strategy fixed --task-id d07 --live-model
```

Only development IDs d01-d08 are accepted by this command. Each result is saved under ignored `work/h2/` with a unique trace ID. Use `--output work/h2/my-new-result.json` for a specific new file; existing results are never overwritten. Terminal execution failures are saved too. Exit codes: 0 completed, 1 saved execution failure, 2 invalid input/configuration/output path. Completed does not mean semantically correct or graded as a pass.

For a custom development question, use `--input path/to/candidate.json` instead of `--task-id`. Its only accepted fields are:

- `task_id`: diagnostic correlation ID; never included in the actual model prompt.
- `question`: current user message.
- `profile`: an ApplicantProfile object with original GPA/test scopes and versions.
- `setup_messages`: earlier user messages to execute in order.
- `program_ids`: explicit user scope, not hidden expected program IDs.
- `as_of_date`: exactly `2026-11-16`, the frozen assessment date.

Raw task records, answer keys, task types, tags, families, expected calls and scoring rubrics are rejected at the candidate boundary. The runner's host loader projects development records by whitelist and never reads reference files. Engine, provider, tools and prompts do not import evaluator modules.

## Strategy behavior

`react` uses Responses API native functions with one selected action per decision. The model sees the current profile, public program identity index, current observations and prior user/assistant turns; it may choose search, program lookup, source lookup, checks or a final answer. A missing source or stale check is fed back as an actual observation. There are no tool calls fabricated from the model's prose.

`fixed` is a classic RAG QA adapter. Each user turn runs exact-filter search, then complete program records and deterministic checks for the explicit user scope or literal lexical program matches, then one final answer call. It does not adapt retrieval to observations or request repairs. Its first operation is always search, including tasks whose requested first action is a direct lookup; a later lookup will not satisfy H3's first-tool-call grader. This is a legitimate baseline limitation to retain, not a reason to inject hidden expected calls.

Both strategies use the same four read-only interfaces, snapshot evidence, model, business rules, conservative tier rubric and task budgets. The policies differ in how they access that evidence. Shared preparation handles explicit profile updates; ambiguous changes are not silently applied. Updates use local validated budget parsing where unambiguous, otherwise one metered structured interpretation call. Setup and interpretation calls count toward the same eight-call task cap.

The final validator rejects unobserved citations/URLs, unsupported formal recommendations and missing current checks. It recomputes constraint and tier evidence independently of the proposed ranking. It does not prove all free-text statements correct; that is H3 grader work.

## Result and trace

The JSON result contains execution status/error, trace ID, current/final answer, before/after profiles, executed conversation, strategy, model/tool counts, actual request count, wall-clock latency, per-call usage and cost estimates, configuration hashes/limits and the complete span tree.

Input and output token counts come from the provider, including failed calls when available. Cached input is a subset of input tokens. Unknown usage and costs stay null and are flagged; they are not reported as measured zeros. `actual_requests` distinguishes provider requests from explicit offline test doubles. The trace records observable actions/observations and structured errors, never private model reasoning or API keys. Previous hidden response state and built-in web tools are not used.

Frozen caps: eight candidate model calls, twelve logical tool calls and 120 seconds for all turns in a task; each request has at most 45 seconds and 1,800 output tokens. There are no automatic API retries. Cache hits still count as tool calls; a third unchanged identical action terminates the execution. Each task/repeat must instantiate a new CandidateRun.

## Bounded live smoke

```powershell
.\.venv\Scripts\python.exe -m scripts.homework.smoke_h2 --live-model
```

This explicitly starts three development probes with a combined ceiling of twelve requests: an induced missing-source Agent recovery, baseline d08 affordability and baseline d07 multi-turn profile update. Results are immediately saved under a new `work/h2/smoke-<uuid>` directory. It does not grade or run formal tasks. Existing results and development failures are retained. Use `--output-dir work/h2/new-attempt-name` for a named new attempt. If interrupted, `--resume` with that same directory continues saved attempts without replacing them; candidate-code changes require a separately labelled attempt.

The completed actual H2 acceptance run used seven requests. Its immutable records, estimates, console-runner incident and limitations are documented in [H2 verification](../docs/verification/H2.md). H3 adds independent graders; H4 adds the full scheduling/metrics harness.
