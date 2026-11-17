"""Read-only H1 consistency checks. No model calls, grading, or production oracle."""
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from gradmatch.catalog import load_seed
from gradmatch.homework.contracts import CandidateInput, tool_contracts
from gradmatch.homework.dataset import EvalTask, Reference, candidate_input, read_jsonl
from gradmatch.schemas import AdmissionEvidence, ApplicantProfile, EnglishRequirement, TuitionPolicy
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def at(value, path):
    if not re.fullmatch(r"[A-Za-z_0-9]+(?:\.[A-Za-z_0-9]+)*", path):
        raise ValueError(f"Invalid declarative field path: {path}")
    for key in path.split("."):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def normalized_binding(path, value):
    # Historical records omit newly introduced conservative defaults.
    if path == "english":
        return [EnglishRequirement.model_validate(v).model_dump(mode="json") for v in value]
    if path == "tuition":
        return TuitionPolicy.model_validate(value).model_dump(mode="json")
    if path == "admission_evidence":
        return [AdmissionEvidence.model_validate(v).model_dump(mode="json") for v in value]
    return value


def same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def independent_tuition(program, upper):
    """Small independently coded arithmetic oracle using source-backed inputs."""
    policy = program.tuition
    if policy.currency != "USD" or policy.unit_rate_lower is None or not policy.rate_year:
        raise ValueError("No supported tuition arithmetic basis")
    rate = policy.unit_rate_upper if upper and policy.unit_rate_upper is not None else policy.unit_rate_lower
    if policy.basis == "full_program":
        units = Decimal(1)
    elif policy.basis == "per_credit":
        if program.required_credits is None or program.required_credits != policy.required_units_lower:
            raise ValueError("Credit requirement and billable units disagree")
        units = program.required_credits
    elif policy.basis == "per_term":
        units = policy.required_units_upper if upper and policy.required_units_upper is not None else policy.required_units_lower
        if units is None:
            raise ValueError("Missing complete term count")
    else:
        raise ValueError("Unverified complete billing basis")
    extra = policy.additional_required_tuition_upper_usd if upper else policy.additional_required_tuition_lower_usd
    return rate * units + extra


def validate_records(tasks, references, programs, sources, *, formal=True):
    expected_count = 50 if formal else 8
    if len(tasks) != expected_count or len(references) != expected_count:
        raise ValueError(f"Expected {expected_count} tasks and references")
    by_id = {t.id: t for t in tasks}
    ref_map = {r.task_id: r for r in references}
    if len(by_id) != len(tasks) or len(ref_map) != len(references) or set(by_id) != set(ref_map):
        raise ValueError("Task/reference IDs must be unique and match exactly")
    prefix = "t" if formal else "d"
    if set(by_id) != {f"{prefix}{i:02d}" for i in range(1, expected_count + 1)}:
        raise ValueError("Task IDs do not match the declared formal/development split")
    questions = [" ".join(t.question.lower().split()) for t in tasks]
    if len(set(questions)) != len(questions):
        raise ValueError("Duplicate normalized question")
    counts = Counter(t.type for t in tasks)
    edges = sum("edge_case" in t.tags for t in tasks)
    if set(counts) != {"exact", "tool", "rubric", "unanswerable"}:
        raise ValueError("All four slide task types must be represented")
    if formal and (edges < 3 or counts["unanswerable"] < 2):
        raise ValueError("Assignment edge/unanswerable minima are not met")
    program_map = {p.program_id: p for p in programs}
    claim_count, used_sources, touched = 0, set(), set()
    for task in tasks:
        ref = ref_map[task.id]
        if any(pid not in program_map for pid in task.program_ids + ref.required_program_ids + ref.forbidden_formal_program_ids):
            raise ValueError(f"Unknown program reference: {task.id}")
        if task.profile.profile_version != 1:
            raise ValueError("Each task/repeat must begin in a fresh profile version 1")
        if task.rubric and (any(not v.strip() for v in task.rubric) or len(task.rubric) != len(set(task.rubric))):
            raise ValueError(f"Empty/duplicate rubric criterion: {task.id}")
        if len(ref.source_ids) != len(set(ref.source_ids)) or any(s not in sources for s in ref.source_ids):
            raise ValueError(f"Unknown/duplicate reference source ID: {task.id}")
        used_sources.update(ref.source_ids)
        touched.update(task.program_ids + ref.required_program_ids)
        for claim in ref.claims:
            claim_count += 1
            if claim.program_id not in program_map:
                raise ValueError(f"Unknown claim program: {task.id}")
            touched.add(claim.program_id)
            program = program_map[claim.program_id]
            actual = at(program.model_dump(mode="json"), claim.path)
            if not same(actual, claim.value):
                raise ValueError(f"Reference fact differs from frozen catalog: {task.id}/{claim.path}")
            if claim.basis == "snapshot_state":
                if claim.group is not None or claim.source_ids:
                    raise ValueError("Snapshot observations must not impersonate official field bindings")
                continue
            if not claim.group or not claim.source_ids or not set(claim.source_ids) <= set(ref.source_ids):
                raise ValueError(f"Missing official claim provenance: {task.id}")
            for sid in claim.source_ids:
                source = sources.get(sid)
                if (source is None or source.program_id != claim.program_id
                        or source.verification_status != "verified" or claim.group not in source.field_groups
                        or sid not in program.field_sources.get(claim.group, [])):
                    raise ValueError(f"Cross-program or invalid field provenance: {task.id}/{sid}")
                supported = False
                for path, value in source.verified_values[claim.group].items():
                    value = normalized_binding(path, value)
                    if path == claim.path:
                        supported |= same(value, claim.value)
                    elif claim.path.startswith(path + "."):
                        supported |= same(at(value, claim.path[len(path)+1:]), claim.value)
                if not supported:
                    raise ValueError(f"Source does not bind the cited fact: {task.id}/{claim.path}")
        for assertion in ref.source_assertions:
            if assertion.source_id not in ref.source_ids:
                raise ValueError("Source text assertion lacks a declared citation")
            text = " ".join(getattr(sources[assertion.source_id], assertion.field).split())
            if " ".join(assertion.contains.split()) not in text:
                raise ValueError(f"Source text does not support the reference: {task.id}")
        if not ref.claims and not ref.source_assertions and not ref.preserve_other_profile_fields and not ref.absence_query:
            raise ValueError(f"Reference lacks an explicit factual/input basis: {task.id}")
        for item in ref.expected_checks:
            if item.program_id not in program_map:
                raise ValueError("Expected check names an unknown program")
            if item.rule_id not in {"identity", "intake", "gpa", "english", "prerequisites", "tuition", "deadline", "degree", "gre", "remaining_eligibility"}:
                raise ValueError("Unknown expected rule dimension")
        if ref.expected_profile_changes:
            if not set(ref.expected_profile_changes) <= set(ApplicantProfile.model_fields) - {"profile_version"}:
                raise ValueError("Unsupported expected profile update")
            values = task.profile.model_dump(mode="json")
            values.update(ref.expected_profile_changes)
            ApplicantProfile.model_validate(values)
            if not task.setup_messages:
                raise ValueError("A follow-up state expectation requires prior session setup")
        if ref.absence_query:
            query = ref.absence_query.casefold()
            if task.type != "unanswerable" or any(query in (p.university+' '+p.program_name).casefold() for p in programs):
                raise ValueError("Missing-program reference is not absent from the frozen catalog")
        if task.type == "exact":
            basis = ref.exact_basis
            if basis is None or basis.program_id not in program_map:
                raise ValueError("Exact answer needs a checkable field/arithmetic basis")
            program = program_map[basis.program_id]
            if basis.kind == "field":
                if not basis.path or not any(c.program_id == basis.program_id and (basis.path == c.path or basis.path.startswith(c.path+'.')) for c in ref.claims):
                    raise ValueError("Exact field is not covered by a reviewed claim")
                expected = at(program.model_dump(mode="json"), basis.path)
            else:
                expected = independent_tuition(program, basis.kind == "tuition_upper")
            if basis.normalization == "decimal":
                try:
                    agrees = Decimal(task.expected) == Decimal(str(expected))
                except InvalidOperation as error:
                    raise ValueError(f"Exact numeric reference is not a finite decimal: {task.id}") from error
                if not agrees:
                    raise ValueError(f"Exact numeric answer disagrees with independent basis: {task.id}")
            elif str(expected) != task.expected:
                raise ValueError(f"Exact answer disagrees with source field: {task.id}")
        elif ref.exact_basis is not None:
            raise ValueError("Non-exact task cannot smuggle an exact-answer channel")
        if task.type == "tool":
            args = task.expected_call.arguments
            if "program_id" in args and args["program_id"] not in task.program_ids:
                raise ValueError("Expected tool program must be explicitly scoped in the user input")
            if "source_id" in args and args["source_id"] not in ref.source_ids:
                raise ValueError("Expected evidence call lacks reference provenance")
            if "source_id" in args and sources[args["source_id"]].program_id not in task.program_ids:
                raise ValueError("Evidence tool reference is outside the explicitly scoped program")
            if "profile_version" in args and args["profile_version"] != task.profile.profile_version:
                raise ValueError("Expected tool call uses a stale profile version")
            if task.expected_call.name == "search_programs":
                matched = sorted(p.program_id for p in programs if all(v is None or getattr(p, k) == v for k,v in args.items()))
                if matched != sorted(ref.required_program_ids):
                    raise ValueError("Expected search results disagree with the declared exact filters")
        visible = candidate_input(task, date(2026, 11, 16)).model_dump(mode="json")
        if set(visible) != set(CandidateInput.model_fields):
            raise ValueError("Candidate projection differs from its whitelist")
    return {"tasks":len(tasks),"types":dict(sorted(counts.items())),"edge_cases":edges,
        "followup_tasks":sum(bool(t.setup_messages) for t in tasks),"families":len({t.family for t in tasks}),
        "programs_covered":sorted(touched),"reference_source_count":len(used_sources),"checked_fact_claims":claim_count}


def validate_bundle():
    folder = PROJECT_ROOT / "homework"
    manifest = json.loads((folder / "experiment.json").read_text(encoding="utf-8"))
    expected_files = {f"homework/{name}" for name in ["tasks.jsonl","references.jsonl","dev_tasks.jsonl","dev_references.jsonl","tool_contracts.json"]}
    if set(manifest["files"]) != expected_files:
        raise ValueError("The dataset lock must contain exactly the five declared homework artifacts")
    for relative, expected_hash in manifest["files"].items():
        if digest(PROJECT_ROOT / relative) != expected_hash:
            raise ValueError(f"Frozen homework artifact hash mismatch: {relative}")
    if (manifest["catalog_path"] != "data/catalog/m35_seed.json"
            or manifest["tier_rubric_path"] != "config/ranking_rubric.md"):
        raise ValueError("Unexpected catalog/rubric path")
    for path_key, hash_key in [("catalog_path","catalog_sha256"),("tier_rubric_path","tier_rubric_sha256")]:
        if digest(PROJECT_ROOT/manifest[path_key]) != manifest[hash_key]:
            raise ValueError("Frozen catalog or rubric bytes changed")
    if json.loads((folder/'tool_contracts.json').read_text(encoding='utf-8')) != tool_contracts():
        raise ValueError("Tool schemas changed after H1 freeze")
    if (manifest["assessment_date"] != "2026-11-16" or manifest["data_mode"] != "snapshot"
            or manifest["model"] != "gpt-5.4-mini-2026-03-17"
            or manifest["rubric_version"] != "conservative-v1.1"
            or manifest["baseline_repeats"] != 1 or manifest["agent_repeats"] != 3
            or manifest["planned_candidate_executions"] != 200
            or set(manifest["candidate_visibility"]) != set(CandidateInput.model_fields)):
        raise ValueError("Experiment does not match the predeclared H1 contract")
    if manifest["candidate_limits"] != {"max_model_calls_per_task":8,"max_tool_calls_per_task":12,
            "max_task_seconds":120,"model_timeout_seconds":45,"max_output_tokens_per_call":1800,"automatic_model_retries":0}:
        raise ValueError("Candidate resource limits differ from the predeclared H1 contract")
    programs, sources = load_seed()
    if len(programs) != manifest["program_count"] or len(sources) != manifest["source_count"] or data_hash(programs,sources) != manifest["catalog_data_hash"]:
        raise ValueError("Catalog facts differ from the locked experiment")
    tasks=read_jsonl(folder/'tasks.jsonl', EvalTask); refs=read_jsonl(folder/'references.jsonl', Reference)
    dev=read_jsonl(folder/'dev_tasks.jsonl', EvalTask); dev_refs=read_jsonl(folder/'dev_references.jsonl', Reference)
    formal_result=validate_records(tasks,refs,programs,sources)
    dev_result=validate_records(dev,dev_refs,programs,sources,formal=False)
    if ({t.id for t in tasks}&{t.id for t in dev}
            or {" ".join(t.question.lower().split()) for t in tasks}&{" ".join(t.question.lower().split()) for t in dev}
            or {t.family for t in tasks}&{t.family for t in dev}):
        raise ValueError("Formal and development IDs/questions/families must be disjoint")
    return {"status":"passed","checkpoint":"H1","formal":formal_result,"development":dev_result,
        "catalog_data_hash":manifest["catalog_data_hash"],"assessment_date":manifest["assessment_date"],
        "snapshot_hashes":"verified","artifact_hashes":"verified","candidate_projection":"whitelisted",
        "reference_review":"authored and checked against snapshot fields/text; not a claim of human judge calibration",
        "model_api_calls":0,"network_requests":0,"formal_evaluation":"not_run","h2_agent":"not_assessed_by_h1_validator"}
