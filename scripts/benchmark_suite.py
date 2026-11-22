"""Versioned development tasks and isolated scoring rules for GradMatch."""

from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from gradmatch.catalog import load_seed
from gradmatch.community import COMMUNITY_FILE
from gradmatch.directory import INDEX, LINKS
from gradmatch.schemas import ApplicantProfile, Record, TuitionPolicy
from gradmatch.session import LEAF_FIELDS, ROOT_FIELDS, tiering_profile
from gradmatch.storage import PROJECT_ROOT


Category = Literal['initial', 'followup', 'clarification', 'evidence_gap', 'shortfall']
FORMAL_COUNTS = dict(initial=50, followup=50, clarification=40, evidence_gap=40, shortfall=30)
ID = r'^[a-z0-9][a-z0-9_-]*$'
SNAPSHOT_FILES = (COMMUNITY_FILE, INDEX, LINKS)


def hash_json(value):
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def json_file(path):
    return json.loads(path.read_text(encoding='utf-8'))


class SnapshotConfig(Record):
    version: str
    evaluation_date: date
    catalog_seed: str
    snapshot_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


class Submission(Record):
    message: str | None = Field(default=None, min_length=1)
    changes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def check_changes(self):
        if not self.changes and not self.message:
            raise ValueError('A follow-up needs a message or form values.')
        if not self.changes.keys() <= ROOT_FIELDS:
            raise ValueError('Follow-up contains an unsupported form field.')
        return self


class TaskSpec(Record):
    task_id: str = Field(pattern=ID)
    category: Category
    template_family: str = Field(pattern=ID)
    initial_profile_overrides: dict[str, Any] = Field(default_factory=dict)
    initial_message: str | None = Field(default=None, min_length=1)
    followups: list[Submission] = Field(default_factory=list)
    clarification_answers: dict[str, Any] = Field(default_factory=dict)
    max_user_turns: int = Field(default=4, ge=1, le=6)
    withhold_tuition_for: str | None = None

    @model_validator(mode='after')
    def check_task(self):
        if not self.initial_profile_overrides.keys() <= ROOT_FIELDS:
            raise ValueError('Initial profile contains an unsupported field.')
        if not self.clarification_answers.keys() <= ROOT_FIELDS | LEAF_FIELDS:
            raise ValueError('Clarifications contain an unsupported field.')
        if 1 + len(self.followups) > self.max_user_turns:
            raise ValueError('The turn limit is shorter than the script.')
        self.profile()
        return self

    def profile(self):
        return ApplicantProfile.model_validate({**tiering_profile().model_dump(), **self.initial_profile_overrides})


class ProgramExpectation(Record):
    program_id: str
    reason_code: str | None = None
    missing_field: str | None = None
    tier: Literal['Lottery', 'Reach', 'Target', 'Safer'] | None = None


class TaskOracle(Record):
    task_id: str = Field(pattern=ID)
    reference_note: str = Field(min_length=12)
    statuses: list[Literal['completed', 'insufficient_evidence', 'infeasible', 'needs_input']] = Field(min_length=1)
    required_question_fields: list[str] = Field(default_factory=list)
    minimum_preliminary_count: int = Field(default=0, ge=0, le=8)
    maximum_formal_count: int | None = Field(default=None, ge=0)
    formal: list[ProgramExpectation] = Field(default_factory=list)
    excluded: list[ProgramExpectation] = Field(default_factory=list)
    pending: list[ProgramExpectation] = Field(default_factory=list)
    expected_profile_changes: dict[str, Any] = Field(default_factory=dict)
    preserve_other_profile_fields: bool = True

    @model_validator(mode='after')
    def check_oracle(self):
        groups = [{item.program_id for item in group} for group in (self.formal, self.excluded, self.pending)]
        if groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2]:
            raise ValueError('Conflicting final program expectations.')
        if self.maximum_formal_count is not None and len(self.formal) > self.maximum_formal_count:
            raise ValueError('Required recommendations exceed the maximum.')
        if not self.expected_profile_changes.keys() <= ROOT_FIELDS:
            raise ValueError('Oracle expects an unsupported profile field.')
        if not set(self.required_question_fields) <= ROOT_FIELDS | LEAF_FIELDS:
            raise ValueError('Oracle expects an unsupported question.')
        return self


def read_jsonl(path, model):
    rows = {}
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = model.model_validate_json(line)
        except ValueError as error:
            raise ValueError(f'{path}:{number}: {error}') from error
        if item.task_id in rows:
            raise ValueError(f'Duplicate task ID {item.task_id} in {path}.')
        rows[item.task_id] = item
    if not rows:
        raise ValueError(f'No tasks found in {path}.')
    return rows


def load_suite(suite_path, oracle_path, config_path, *, split='development'):
    config = SnapshotConfig.model_validate(json_file(config_path))
    seed = (PROJECT_ROOT / config.catalog_seed).resolve()
    if seed.parent != PROJECT_ROOT / 'data/catalog' or seed.name == 'active.json':
        raise ValueError('Evaluation requires a versioned catalog seed.')
    snapshot = hash_json([json_file(path) for path in (seed, *SNAPSHOT_FILES)])
    if snapshot != config.snapshot_hash:
        raise ValueError(f'Snapshot changed: expected {config.snapshot_hash}, found {snapshot}.')
    programs, sources = load_seed(seed)
    tasks = read_jsonl(suite_path, TaskSpec)
    oracles = read_jsonl(oracle_path, TaskOracle)
    if tasks.keys() != oracles.keys():
        raise ValueError('Tasks and oracles must have the same IDs.')
    if split == 'formal' and Counter(case.category for case in tasks.values()) != FORMAL_COUNTS:
        raise ValueError(f'The formal suite must have category counts {FORMAL_COUNTS}.')
    if split == 'formal':
        development = read_jsonl(PROJECT_ROOT / 'eval/development/tasks.jsonl', TaskSpec)
        if ({case.template_family for case in development.values()}
                & {case.template_family for case in tasks.values()}):
            raise ValueError('The formal suite shares a template family with development.')
    known = {p.program_id for p in programs}
    for task in tasks.values():
        oracle = oracles[task.task_id]
        references = {item.program_id for group in (oracle.formal, oracle.excluded, oracle.pending) for item in group}
        if task.withhold_tuition_for:
            references.add(task.withhold_tuition_for)
        if not references <= known:
            raise ValueError(f'{task.task_id}: unknown program ID {sorted(references - known)}.')
        if len(oracle.statuses) > task.max_user_turns:
            raise ValueError(f'{task.task_id}: expected turns exceed the task turn cap.')
        profile = task.profile().model_dump(mode='json')
        for followup in task.followups:
            profile.update(followup.changes)
            ApplicantProfile.model_validate(profile)
        if oracle.expected_profile_changes:
            ApplicantProfile.model_validate({**task.profile().model_dump(), **oracle.expected_profile_changes})
    return config, (programs, sources), tasks, oracles


def scenario_catalog(dataset, *, withhold_tuition_for):
    """Hide a program's reviewed tuition and source excerpts from the entire execution."""
    programs, sources = dataset
    if not withhold_tuition_for:
        return programs, sources
    retained = {sid: source for sid, source in sources.items() if source.program_id != withhold_tuition_for}
    adjusted = []
    for program in programs:
        if program.program_id == withhold_tuition_for:
            program = program.model_copy(update={
                'tuition': TuitionPolicy(), 'field_sources': {}, 'notes': [],
                'goal_features': [], 'admission_evidence': [], 'application_materials': [],
            }, deep=True)
        adjusted.append(program)
    return adjusted, retained
