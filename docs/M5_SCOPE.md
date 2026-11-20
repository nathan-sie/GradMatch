# M5: executable plans and observation-triggered revisions

The third strategy, `plan`, asks the same configured model for a structured 3–6-step plan. Code validates the plan, binds current profile/evidence versions, executes the existing five tools and checks each completion criterion. The UI shows steps, status, revision reasons and result references. Plans do not contain executable code or arbitrary URLs.

## Execution contract

Each step has `step_id`, `tool`, `program_ids`, `target_fields`, `source_id`, `depends_on`, `status`, `done_criteria`, `requested_fields` and `question`. Model-authored statuses must be `pending`. Only code can mark a step `running`, `done`, `failed`, `skipped` or `blocked`. Dependencies must refer to earlier steps. Ranking depends on current checks; final validation depends on ranking. Each plan has exactly one ranking step followed by final validation.

Empty scope on checks/ranking means the current retrieved candidates. Registered source IDs identify official pages, with one owning program and requested field groups. Only live mode permits fetching. A live check with explicit `target_fields` requests those critical source facts; an ordinary snapshot gap or an applicant GPA scope mismatch is retained as unknown, without automatic source repair.

Ranking uses the shared automatic validator. The plan's validation step refers to that actual validation observation rather than repeating the tool. A task finishes only after all steps are done and validation matches the current profile/evidence. The shared validator owns the overall result status. Its `MODEL_STATUS_CORRECTED` finding is retained in the legacy audit list and `validation_warnings`, but does not require another paid decision; `validation_passed` requires that every substantive error is absent. Eligibility, tier, version and citation errors remain blocking for every strategy. A completed unchanged plan can be reused without another model request, including when paid calls are disabled. The response explicitly labels reuse. Profile/date/evidence changes invalidate old checks; new deterministic checks with paid calls disabled are not labelled as reuse of an old plan.

## Revision triggers and limits

Code owns triggers: `PROFILE_UPDATED`, `ASSESSMENT_DATE_CHANGED`, unplanned `EVIDENCE_CHANGED`, `USER_REQUEST_UPDATED`, `TOOL_FAILURE`, `MISSING_EVIDENCE`, `SOURCE_CONFLICT`, `VALIDATION_FAILED`, `DONE_CRITERIA_FAILED` or `PLAN_INVALID`. Planned successful evidence acquisition updates the expected version, so it does not itself cause an extra revision. Source conflicts remain unknown. Failed or invalid plans and their observations stay in history; there is no fabricated completion.

The initial plan plus at most **three** replans are allowed per task. Replans count before calling the model, including invalid responses. Fixed, ReAct and Plan-and-replan share the same model, catalog, tools, ranking rubric, validator and cumulative ceilings: 16 model attempts, 20 tools, 16 page requests, 6 user turns, 120 service seconds per turn and 300 per task. Plan requests and extraction/ranking requests all consume the same model allowance. No automatic provider retry is added.

Only explicit profile submission or narrow parsed updates change the profile. User questions pause through the same pure LangGraph interrupt node. A new driver resumes the existing per-session/task/strategy graph; replaying a request ID returns its receipt without executing a model or tool. Session plans and evidence overlays never write to the public SQLite database.

## Verification

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_m5
.\.venv\Scripts\python.exe -m scripts.run_task --help
```

The first command runs regression checks and a three-strategy fixture pilot at three fictional budget levels. **Fixtures test wiring, not model quality.** No final-project accuracy, latency, token or cost advantage is claimed. It never invokes the local API key. Evidence goes to a fresh ignored `work/m5/<id>/` directory; prior attempts are preserved.

For actual hosted acceptance, select **Plan-and-replan agent**, **Reviewed snapshots**, load the fictional **USD 140,000 tiering example**, enable paid calls and generate. Inspect the initial completed plan and the supported MSAII Lottery planning label. Submit `Change my tuition budget to 100000`: expect a `PROFILE_UPDATED` revision, current checks/ranking/validation, and MSAII excluded for tuition. Download the session. Re-running with no changes should make zero new model requests. This controlled flow needs two plan requests and two ranking requests when successful; the task-wide replan limit bounds it to eight requests even if revisions are necessary. Do not submit extra free-text requests during that bounded check.

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_m5 --session 'C:\path\to\downloaded-session.json'
```

The optional session inspection checks actual provider response IDs, usage totals, current completed steps without substantive errors, a profile-triggered revision and budget exclusion. Its saved proof omits messages and the full applicant profile. It does not call a model.

## Boundaries

M5 does not broaden the catalog or invent missing Target/Safer case evidence. The current reviewed set remains 10 programs and 30 sources; only one program supports the pilot Lottery recommendation. The 210-task benchmark and 50 safety prompts remain M6/M7. The separate 50-task homework branch and its frozen results are unchanged. Stop for user acceptance before M6.
