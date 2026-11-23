"""In-memory evidence changes for snapshot benchmark scenarios."""

import hashlib
import json
from typing import Any, Literal

from pydantic import Field, model_validator

from gradmatch.agent_models import GROUP_FIELDS
from gradmatch.schemas import ProgramRecord, Record


MASKED_FIELDS = {
    **GROUP_FIELDS,
    'tuition_minimum': {'tuition'},
    'application_materials': {'application_materials'},
    'remaining_eligibility': {'eligibility_review_complete'},
    'goal_features': {'goal_features'},
    'admission_evidence': {'admission_evidence'},
}


class EvidenceOverlay(Record):
    program_id: str
    field_group: str
    mode: Literal['missing', 'stale', 'conflict']
    conflicting_values: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def check_fields(self):
        if self.field_group not in MASKED_FIELDS:
            raise ValueError('Unknown evidence field group.')
        if (self.mode == 'conflict') != bool(self.conflicting_values):
            raise ValueError('A conflict requires explicit alternative field values.')
        if not self.conflicting_values.keys() <= MASKED_FIELDS[self.field_group]:
            raise ValueError('Alternative values must belong to the affected field group.')
        return self


def projected_source(source, groups, *, source_id=None, values=None, status=None):
    """Keep retained typed bindings and discard excerpts that can mention withheld facts."""
    bindings = values if values is not None else {group: source.verified_values[group] for group in groups}
    identifier = source_id or source.source_id
    fingerprint = hashlib.sha256(json.dumps(
        [source.content_hash, identifier, groups, bindings, status], sort_keys=True,
    ).encode('utf-8')).hexdigest()
    return source.model_copy(update={
        'source_id': identifier,
        'field_groups': groups,
        'verified_values': bindings,
        'verification_status': status or source.verification_status,
        'source_excerpt': '',
        'fact_summary': 'Offline benchmark projection of source bindings.',
        'locator': 'Synthetic benchmark evidence',
        'snapshot_path': f'benchmark://{identifier}',
        'content_hash': fingerprint,
    }, deep=True)


def apply_overlay(dataset, overlay):
    """Make current rules unavailable while preserving unrelated official bindings."""
    programs, sources = dataset
    program = next((p for p in programs if p.program_id == overlay.program_id), None)
    if program is None:
        raise ValueError(f'Unknown overlay program: {overlay.program_id}')
    group = overlay.field_group
    active_ids = program.field_sources.get(group, [])
    if not active_ids:
        raise ValueError(f'Overlay group has no reviewed source: {program.program_id}/{group}')
    fields = MASKED_FIELDS[group] | {'notes'}
    if group == 'credits' and program.tuition.basis == 'per_credit':
        fields |= {'tuition'}
    original = program.model_dump(mode='json')
    retained_sources = {sid: source for sid, source in sources.items() if source.program_id != program.program_id}
    for sid, source in sources.items():
        if source.program_id != program.program_id:
            continue
        retained_groups = [
            name for name in source.field_groups if name != group and not any(
                path.split('.')[0] in fields
                and not (path.startswith('notes.') and name == 'duplicate_advanced_degree')
                for path in source.verified_values[name]
            )
        ]
        if retained_groups:
            retained_sources[sid] = projected_source(source, retained_groups)
    links = {}
    for name, ids in program.field_sources.items():
        remaining = [
            sid for sid in ids
            if sid in retained_sources and name.removeprefix('history:') in retained_sources[sid].field_groups
        ]
        if remaining:
            links[name] = remaining
    if overlay.mode != 'missing':
        source = sources[active_ids[0]]
        archived = projected_source(source, [group], source_id=f'benchmark-{group}-{overlay.mode}-{source.source_id}',
                                    status=overlay.mode)
        retained_sources[archived.source_id] = archived
        links[group] = [archived.source_id]
        if overlay.mode == 'conflict':
            alternative = ProgramRecord.model_validate({**original, **overlay.conflicting_values}).model_dump(mode='json')
            if all(original[key] == alternative[key] for key in overlay.conflicting_values):
                raise ValueError('Conflicting values must differ from the pinned program.')
            alternate = projected_source(
                source, [group], source_id=f'benchmark-{group}-alternative-{source.source_id}', status='conflict',
                values={group: {key: alternative[key] for key in overlay.conflicting_values}},
            )
            retained_sources[alternate.source_id] = alternate
            links[group].append(alternate.source_id)
    defaults = {key: ProgramRecord.model_fields[key].get_default(call_default_factory=True) for key in fields}
    # Preserve the independent duplicate-degree condition when its evidence is bound to a note.
    duplicate_links = links.get('duplicate_advanced_degree', [])
    if duplicate_links:
        notes = [''] * len(program.notes)
        for source_id in duplicate_links:
            for path, value in retained_sources[source_id].verified_values['duplicate_advanced_degree'].items():
                if path.startswith('notes.'):
                    notes[int(path.removeprefix('notes.'))] = value
        defaults['notes'] = notes
    updated = ProgramRecord.model_validate({**original, **defaults, 'field_sources': links})
    return [updated if p.program_id == program.program_id else p for p in programs], retained_sources
