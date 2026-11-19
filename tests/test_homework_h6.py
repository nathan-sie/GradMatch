"""Submission integrity and factual failure attribution; no model requests."""
import csv
import io
import json
import zipfile
import pytest
from gradmatch.homework.contracts import CandidateInput
from gradmatch.homework.submission import (
    PACKAGE_NAME,package_payloads,regression_fixture,safe_relative,scan_payloads,
    selected_failure,verify_payloads,
)
from gradmatch.storage import PROJECT_ROOT
from scripts.homework.verify_submission import read_archive


def test_failure_is_an_actual_model_action_order_error():
    case=selected_failure()
    saved=json.loads((PROJECT_ROOT/'docs/verification/h6/failure_case.json').read_text(encoding='utf-8'))
    assert case==saved
    assert case['failure_class']=='model_action_order'
    assert case['actual_first_call']['name']=='get_program'
    assert case['expected_first_call']==case['later_call']
    assert case['tool_failures']==0 and case['final_answer_validated']
    assert case['english_check']['status']=='fail' and case['repeat_vector']==[True,False,True]
    assert not case['fix_applied_to_frozen_experiment']


def test_proposed_regression_uses_a_separate_candidate_only_input():
    value,reference=regression_fixture()
    candidate=CandidateInput.model_validate(value)
    assert candidate.profile.profile_version==3
    assert reference['expected_first_call']['arguments']['profile_version']==3
    assert reference['not_in_formal_task_set']
    assert 'expected_first_call' not in value and 'rubric' not in value
    task_ids={json.loads(line)['id'] for line in (PROJECT_ROOT/'homework/tasks.jsonl').read_text(encoding='utf-8').splitlines()}
    assert candidate.task_id not in task_ids


@pytest.mark.parametrize('name',['','.', '../outside','/absolute','C:/drive','folder\\file','folder/../file','a//b','./file'])
def test_archive_paths_cannot_escape_or_have_aliases(name):
    with pytest.raises(ValueError):safe_relative(name)


@pytest.mark.parametrize('name',['.env','.streamlit/secrets.toml','data/gradmatch.db','work/record.json'])
def test_private_files_are_rejected(name):
    with pytest.raises(ValueError):scan_payloads({name:b'private'})


def test_configured_credentials_are_checked_without_disclosing_the_value():
    credential=b'synthetic-credential-for-scanning'
    with pytest.raises(ValueError,match='no value was printed'):
        scan_payloads({'report.md':b'accidental '+credential},known_key=credential)
    scan_payloads({'.env.example':b'OPENAI_API_KEY=\nMODEL_ENABLED=false\n'})


@pytest.fixture(scope='module')
def payloads():return package_payloads()


def test_package_contains_frozen_tasks_and_all_actual_records(payloads):
    checks=verify_payloads(payloads)
    assert checks['formal_tasks']==50 and checks['formal_executions']==200
    assert checks['raw_candidate_records']==200
    assert payloads['tasks.jsonl']==(PROJECT_ROOT/'homework/tasks.jsonl').read_bytes()
    assert 'docs/verification/h6/verification.json' not in payloads
    assert payloads['report.pdf'].startswith(b'%PDF-')
    rows=list(csv.DictReader(io.StringIO(payloads['submission_results.csv'].decode())))
    assert [row['accuracy'] for row in rows]==['0.78','0.94']
    assert rows[0]['pass@3']=='N/A' and rows[1]['pass@3']=='0.98' and rows[1]['pass^3']=='0.76'
    assert b'________________________' in payloads['TEAM.md']


def test_manifest_detects_modified_raw_evidence(payloads):
    changed=dict(payloads)
    name='docs/verification/h5/formal/entries/t26--react--r2/candidate.json'
    changed[name]+=b' '
    with pytest.raises(ValueError,match='integrity'):verify_payloads(changed)


def test_manifest_detects_missing_raw_evidence(payloads):
    changed=dict(payloads)
    del changed['docs/verification/h5/formal/entries/t26--react--r2/grade.json']
    with pytest.raises(ValueError,match='members'):verify_payloads(changed)


@pytest.mark.parametrize('member',[PACKAGE_NAME+'/../outside','other/tasks.jsonl'])
def test_zip_reader_rejects_unexpected_layout(tmp_path,member):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as stream:stream.writestr(member,b'data')
    with pytest.raises(ValueError):read_archive(archive)


def test_zip_reader_rejects_duplicate_members(tmp_path):
    archive=tmp_path/'duplicate.zip'
    with zipfile.ZipFile(archive,'w') as stream:
        stream.writestr(PACKAGE_NAME+'/tasks.jsonl',b'first')
        with pytest.warns(UserWarning):stream.writestr(PACKAGE_NAME+'/tasks.jsonl',b'second')
    with pytest.raises(ValueError,match='Duplicate'):read_archive(archive)
