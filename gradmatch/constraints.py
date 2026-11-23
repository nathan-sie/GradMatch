"""Deterministic eligibility dimensions; unknown evidence never passes."""

from calendar import monthrange
from datetime import date
from decimal import Decimal
import json

from gradmatch.schemas import (
    ApplicantProfile, CheckStatus, ConstraintCheck, ConstraintReport,
    ProgramRecord, SourceRecord, TuitionEstimate, TuitionPolicy, EnglishRequirement, AdmissionEvidence,
)


def estimate_tuition(policy: TuitionPolicy) -> TuitionEstimate:
    base = dict(rate_year=policy.rate_year, assumptions=list(policy.assumptions),
                mandatory_fees_usd=policy.mandatory_fees_usd)
    if policy.currency != "USD":
        return TuitionEstimate(reason_code="UNSUPPORTED_CURRENCY", **base)
    if policy.basis == "unknown" or (policy.unit_rate_lower is None and policy.unit_rate_upper is None) or policy.rate_year is None:
        return TuitionEstimate(reason_code="MISSING_RATE", **base)
    units_low = Decimal("1") if policy.basis == "full_program" else policy.required_units_lower
    units_high = Decimal("1") if policy.basis == "full_program" else (policy.required_units_upper or units_low)
    if units_high is None or (policy.unit_rate_lower is not None and units_low is None):
        return TuitionEstimate(reason_code="MISSING_TOTAL_UNITS", **base)
    if policy.unit_rate_lower is None:
        return TuitionEstimate(
            lower_usd=None,
            upper_usd=policy.unit_rate_upper * units_high + policy.additional_required_tuition_upper_usd,
            formula=f"At most {policy.unit_rate_upper} USD × {units_high} ({policy.basis})"
                + (f" + at most {policy.additional_required_tuition_upper_usd} USD required additional tuition"
                   if policy.additional_required_tuition_upper_usd else "")
                + "; no verified minimum or exact bill",
            reason_code="MAXIMUM_ONLY_TUITION_BOUND", **base,
        )
    rate_high = policy.unit_rate_upper if policy.unit_rate_upper is not None else policy.unit_rate_lower
    return TuitionEstimate(
        lower_usd=policy.unit_rate_lower * units_low + policy.additional_required_tuition_lower_usd,
        upper_usd=rate_high * units_high + policy.additional_required_tuition_upper_usd,
        formula=f"{policy.unit_rate_lower}–{rate_high} USD × {units_low}–{units_high} ({policy.basis})"
            + (f" + {policy.additional_required_tuition_lower_usd}–{policy.additional_required_tuition_upper_usd} USD required additional tuition"
               if policy.additional_required_tuition_upper_usd else ""),
        reason_code="PUBLISHED_RATE_ESTIMATE", **base,
    )


def evidence_ids(program: ProgramRecord, group: str, sources: dict[str, SourceRecord],
                 profile: ApplicantProfile) -> list[str]:
    ids = program.field_sources.get(group, [])
    if not ids:
        return []
    for source_id in ids:
        source = sources.get(source_id)
        if (source is None or source.program_id != program.program_id
                or source.verification_status != "verified" or group not in source.field_groups
                or source.url.host not in program.allowed_official_hosts
                or (source.applicable_intake is not None
                    and (profile.intake is None or source.applicable_intake != profile.intake.key))):
            return []
        bindings = source.verified_values.get(group, {})
        if not bindings:
            return []
        document = program.model_dump(mode="json")
        for path, expected in bindings.items():
            actual = document
            try:
                for key in path.split("."):
                    actual = actual[int(key)] if isinstance(actual, list) else actual[key]
            except (KeyError, IndexError, TypeError, ValueError):
                return []
            # Old immutable snapshots omit fields added with conservative defaults.
            # Normalize expected values through the same schema; changed new values
            # still fail the exact comparison and need new evidence.
            if path == "english":
                expected = [EnglishRequirement.model_validate(v).model_dump(mode="json") for v in expected]
            elif path == "tuition":
                expected = TuitionPolicy.model_validate(expected).model_dump(mode="json")
            elif path == "admission_evidence":
                expected = [AdmissionEvidence.model_validate(v).model_dump(mode="json") for v in expected]
            if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                return []
    return list(ids)


def applicable_deadline_rounds(profile: ApplicantProfile, program: ProgramRecord):
    if profile.intake is None:
        return []
    audiences = {"all", profile.applicant_category}
    if profile.applicant_category == "international" and profile.study_mode == "full_time":
        audiences.add("international_full_time")
    if profile.study_mode == "part_time":
        audiences.add("part_time")
    return [round_ for round_ in program.deadlines
            if round_.intake.key == profile.intake.key and round_.audience in audiences]


def check_constraints(profile: ApplicantProfile, program: ProgramRecord,
                      sources: dict[str, SourceRecord], *, as_of: date, data_mode="snapshot") -> ConstraintReport:
    checks = []
    policy_only_english = (not program.english and not program.english_not_required
        and not program.field_sources.get('english') and not program.field_sources.get('english_minimum'))

    def add(group, status, code, explanation, warnings=None):
        source_ids=evidence_ids(program,group,sources,profile)
        if group == 'english' and not source_ids:
            source_ids = evidence_ids(program, 'english_minimum', sources, profile)
        if group == 'english' and not source_ids and status == 'unknown' and policy_only_english:
            source_ids = evidence_ids(program, 'english_policy', sources, profile)
        if group=='tuition' and estimate.reason_code=='MINIMUM_ONLY_TUITION_BOUND':
            source_ids=evidence_ids(program,'tuition_minimum',sources,profile)
        if group=='tuition' and estimate.reason_code=='MAXIMUM_ONLY_TUITION_BOUND':
            source_ids=list(dict.fromkeys(source_ids+evidence_ids(program,'tuition_upper',sources,profile)))
        if group=='tuition' and program.tuition.basis=='per_credit':
            source_ids=list(dict.fromkeys(source_ids+evidence_ids(program,'credits',sources,profile)))
        checks.append(ConstraintCheck(rule_id=group, status=status, reason_code=code,
            explanation=explanation, source_ids=source_ids,
            warnings=warnings or []))

    def supported(group):
        return bool(evidence_ids(program, group, sources, profile))

    add("identity", "pass" if supported("identity") else "unknown", "OFFICIAL_IDENTITY" if supported("identity") else "MISSING_IDENTITY_EVIDENCE",
        "Program identity is supported by the corresponding official website." if supported("identity") else "Applicable official evidence for the program identity is missing.")

    if profile.intake is None:
        add("intake", "unknown", "MISSING_INTAKE", "Specify the intake year and term.")
    elif not supported("intake"):
        add("intake", "unknown", "INTAKE_NOT_VERIFIED", "This intake is not verified. Prior-year information is not automatically carried forward.")
    elif profile.intake.key in {i.key for i in program.closed_intakes}:
        add("intake", "fail", "INTAKE_CLOSED", "Official evidence indicates that this intake is closed.")
    elif profile.intake.key in {i.key for i in program.supported_intakes}:
        add("intake", "pass", "INTAKE_SUPPORTED", "Official information supports this intake.")
    else:
        add("intake", "unknown", "INTAKE_MISMATCH", "The available evidence does not establish the applicant's selected intake.")

    requirement = program.gpa
    if requirement is not None and requirement.no_hard_minimum and supported("gpa"):
        add("gpa", "not_applicable", "NO_HARD_GPA_MINIMUM", "The applicable official rule explicitly sets no hard GPA minimum; competitiveness still needs assessment.")
    elif profile.gpa is None:
        add("gpa", "unknown", "MISSING_GPA", "The GPA and its original scale have not been provided.")
    elif requirement is None or not supported("gpa"):
        add("gpa", "unknown", "GPA_RULE_NOT_VERIFIED", "No applicable GPA threshold has been verified.")
    elif requirement.minimum is None:
        add("gpa", "unknown", "RECOMMENDATION_NOT_HARD_MINIMUM", "The published GPA is a recommendation. It does not establish that all GPA eligibility requirements are met.")
    elif not requirement.accepted_scopes:
        add("gpa", "unknown", "GPA_SCOPE_NOT_VERIFIED", "The official GPA calculation scope has not been verified. An unspecified scope cannot establish eligibility.")
    elif profile.gpa.scale != requirement.scale:
        add("gpa", "unknown", "GPA_SCALE_MISMATCH", "The GPA scales cannot be compared directly. No automatic conversion is performed.")
    elif profile.gpa.scope not in requirement.accepted_scopes:
        add("gpa", "unknown", "GPA_SCOPE_MISMATCH", "The GPA calculation scopes differ, such as overall GPA versus the last 60 semester credits.")
    elif profile.gpa.value < requirement.minimum:
        if requirement.below_minimum_review_possible:
            add("gpa", "unknown", "GPA_EXCEPTION_REQUIRES_REVIEW", "The GPA is below the published minimum, and special review or consultation may apply. Manual verification is required.")
        else:
            add("gpa", "fail", "GPA_BELOW_MINIMUM", "The GPA is below the explicit hard minimum on the same scale and calculation scope.")
    else:
        add("gpa", "pass", "GPA_MEETS_MINIMUM", "The GPA meets the verified minimum. This does not establish admission competitiveness.")

    score = profile.english
    english_rule = next((rule for rule in program.english if score and rule.version == score.version), None)
    if program.english_not_required and supported("english"):
        add("english", "not_applicable", "ENGLISH_NOT_REQUIRED", "The applicable official rule explicitly does not require an English test.")
    elif score is None:
        add("english", "unknown", "MISSING_ENGLISH", "No verifiable English score is available. Passing scores or exemptions are not assumed.")
    elif english_rule is None or not (supported("english") or supported("english_minimum")):
        explanation = "The program's requirement for this English test version is not verified."
        if policy_only_english and supported('english_policy'):
            explanation += " The cited policy review does not establish an applicable numerical threshold or complete conditions. Historical or typical admitted scores are not assumed to be current minimums."
        add("english", "unknown", "ENGLISH_RULE_NOT_VERIFIED", explanation)
    elif score.test_date and ((score.version == "toefl_120" and score.test_date >= date(2026, 1, 21))
                              or (score.version == "toefl_6" and score.test_date < date(2026, 1, 21))):
        add("english", "unknown", "TOEFL_VERSION_DATE_MISMATCH", "The test date and selected TOEFL version do not match. Verify the score basis; no conversion is performed.")
    elif score.total < english_rule.minimum_total:
        add("english", "fail", "ENGLISH_TOTAL_BELOW_MINIMUM", "The English overall score is below the hard minimum for the same test version.")
    elif any(score.subscores.get(key) is not None and score.subscores[key] < minimum
             for key, minimum in english_rule.minimum_subscores.items()):
        add("english", "fail", "ENGLISH_SUBSCORE_BELOW_MINIMUM", "A required English subscore is below the hard minimum.")
    elif any(key not in score.subscores for key in english_rule.minimum_subscores):
        add("english", "unknown", "MISSING_ENGLISH_SUBSCORES", "Required English subscores are missing.")
    elif not supported("english"):
        add("english", "unknown", "ENGLISH_MINIMUM_ONLY", "The stated score floor is met, but test validity, program conditions or exemption rules still need review. A score floor alone does not establish English eligibility.")
    elif english_rule.validity_years is not None and score.test_date is None:
        add("english", "unknown", "MISSING_ENGLISH_TEST_DATE", "The test date is missing, so score validity cannot be determined.")
    elif score.test_date and score.test_date > as_of:
        add("english", "unknown", "ENGLISH_TEST_IN_FUTURE", "The test date is later than the assessment date.")
    else:
        expiry = None
        cutoff = english_rule.minimum_test_date
        if (profile.degree and profile.degree.country and profile.degree.country.upper() == "US"
                and profile.degree.completion in {"completed", "expected_before_enrollment"}
                and english_rule.us_degree_minimum_test_date):
            cutoff = english_rule.us_degree_minimum_test_date
        if cutoff and score.test_date is None:
            add("english", "unknown", "MISSING_ENGLISH_TEST_DATE", "A test date is required to check the intake-specific score cutoff.")
        elif cutoff and score.test_date < cutoff:
            add("english", "fail", "ENGLISH_BEFORE_INTAKE_CUTOFF", "The test predates the verified intake-specific cutoff.")
        else:
            if not cutoff and english_rule.validity_years is not None:
                year = score.test_date.year + english_rule.validity_years
                expiry = date(year, score.test_date.month, min(score.test_date.day, monthrange(year, score.test_date.month)[1]))
            expired = expiry and (as_of > expiry if english_rule.valid_on_anniversary else as_of >= expiry)
            if expired:
                add("english", "fail", "ENGLISH_EXPIRED", "The English score has expired as of the application assessment date.")
            else:
                warnings = []
                conditional_review = (english_rule.recommended_total is not None
                    and score.total < english_rule.recommended_total and supported('english_conditional_review'))
                if english_rule.recommended_total is not None and score.total < english_rule.recommended_total:
                    warnings.append(english_rule.condition_below_recommended or "Below the officially recommended score.")
                if supported('english_term_validity'):
                    warnings.append('The score-date cutoff uses the published Fall 2027 instruction calendar; calendar changes require a fresh review. No exemption is assumed.')
                if conditional_review:
                    add('english', 'unknown', 'ENGLISH_CONDITIONAL_REVIEW', 'The score is in a conditional or limited-status range. Program approval and language conditions still need review.', warnings)
                else:
                    add("english", "pass", "ENGLISH_MEETS_MINIMUM", "The English score meets the verified minimum. Additional conditions may still apply.", warnings)

    if not supported("prerequisites") or not program.prerequisites_complete:
        add("prerequisites", "unknown", "PREREQUISITES_REQUIRE_REVIEW", "Prerequisite rules are incomplete, or individual deficiencies may be reviewed. Manual verification is required.")
    elif supported('prerequisite_background_review') and (profile.degree is None or profile.degree.field not in {'CS', 'ECE'}):
        add('prerequisites', 'unknown', 'BACKGROUND_EQUIVALENCY_REQUIRES_REVIEW', 'The program considers other backgrounds individually. Computer science preparation and relevant experience need university review; recommended courses are not automatic rejection rules.')
    elif not program.required_topics:
        add("prerequisites", "not_applicable", "NO_REQUIRED_TOPICS", "The verified rule specifies no mandatory coursework topics.")
    elif any(profile.coursework.get(topic) is False for topic in program.required_topics):
        if supported('prerequisite_review'):
            add('prerequisites', 'unknown', 'COURSEWORK_DEFICIENCY_REQUIRES_REVIEW', 'The declared preparation has a gap. The program reviews alternative preparation or deficiencies individually; admission or an equivalency waiver is not assumed.')
        else:
            add("prerequisites", "fail", "MISSING_REQUIRED_COURSEWORK", "The applicant explicitly lacks at least one mandatory coursework topic or skill.")
    elif any(profile.coursework.get(topic) is not True for topic in program.required_topics):
        add("prerequisites", "unknown", "COURSEWORK_NOT_PROVIDED", "Required coursework or skills have not been fully specified.")
    else:
        add("prerequisites", "pass", "COURSEWORK_SELF_REPORTED", "Checked against the applicant's explicit self-report for each mandatory topic. This does not replace the university's equivalency assessment.")

    estimate = estimate_tuition(program.tuition)
    ceiling_only = estimate.reason_code == 'MAXIMUM_ONLY_TUITION_BOUND'
    ceiling_ids = evidence_ids(program, 'tuition_upper', sources, profile)
    ceiling_paths = {path for sid in ceiling_ids for path in sources[sid].verified_values.get('tuition_upper', {})}
    ceiling_required = {'tuition.currency', 'tuition.basis', 'tuition.unit_rate_lower', 'tuition.unit_rate_upper',
                        'tuition.required_units_lower', 'tuition.required_units_upper', 'tuition.rate_year', 'tuition.assumptions'}
    # A ceiling needs its own reviewed rate, scope and billing-unit evidence.
    # Removing one dependency cannot turn a partial quote into an affordability pass.
    if ceiling_only and not (ceiling_ids and ('tuition' in ceiling_paths or ceiling_required <= ceiling_paths)):
        estimate = TuitionEstimate(reason_code='MISSING_TUITION_CEILING_EVIDENCE', assumptions=list(program.tuition.assumptions))
    if ceiling_only and program.tuition.basis in {'per_term', 'per_year'} and profile.study_mode != 'full_time':
        estimate = TuitionEstimate(reason_code='TUITION_SCHEDULE_SCOPE_UNVERIFIED', assumptions=list(program.tuition.assumptions))
    if (not supported("tuition") or (program.tuition.basis == "per_credit" and (
            not supported("credits") or program.required_credits is None
            or (not ceiling_only and program.tuition.required_units_lower != program.required_credits)
            or (ceiling_only and program.tuition.required_units_upper != program.required_credits)
            or (program.tuition.required_units_upper is not None
                and program.tuition.required_units_upper != program.required_credits)))):
        estimate = TuitionEstimate(reason_code="MISSING_TUITION_EVIDENCE", assumptions=list(program.tuition.assumptions))
    floor_ids=evidence_ids(program,'tuition_minimum',sources,profile)
    required_floor_paths={'tuition.currency','tuition.unit_rate_lower','tuition.required_units_lower','tuition.rate_year'}
    floor_paths={path for sid in floor_ids for path in sources[sid].verified_values.get('tuition_minimum',{})}
    policy=program.tuition
    floor_applies = policy.basis not in {"per_term", "per_year"} or profile.study_mode == "full_time"
    if (estimate.upper_usd is None and required_floor_paths <= floor_paths
            and policy.currency=='USD' and policy.unit_rate_lower is not None
            and policy.required_units_lower is not None and policy.rate_year and floor_applies):
        unit_label = {"per_term": "billing terms", "per_year": "academic years", "per_credit": "credits"}.get(policy.basis, "units")
        estimate=TuitionEstimate(lower_usd=policy.unit_rate_lower*policy.required_units_lower,
            upper_usd=None,formula=f"At least {policy.required_units_lower} {unit_label} × {policy.unit_rate_lower} USD; no verified upper bound",
            rate_year=policy.rate_year,reason_code='MINIMUM_ONLY_TUITION_BOUND',assumptions=list(policy.assumptions))
    if profile.tuition_budget_usd is None:
        add("tuition", "unknown", "MISSING_BUDGET", "A full-program tuition budget is missing.")
    elif (profile.budget_basis == "published_rate_estimate" and estimate.upper_usd is None
          and estimate.lower_usd is not None and estimate.lower_usd > profile.tuition_budget_usd):
        add("tuition", "fail", "TUITION_MINIMUM_EXCEEDS_BUDGET", "The verified tuition minimum at the stated published rates already exceeds the budget; the final full-program amount remains unknown.")
    elif estimate.upper_usd is None:
        add("tuition", "unknown", estimate.reason_code, "A verified full-program tuition upper bound is missing. A known minimum does not establish affordability; fees or living budgets cannot substitute for tuition.")
    elif profile.budget_basis == "guaranteed_final" and (
            profile.intake is None or program.tuition.guaranteed_for_intake != profile.intake.key):
        add("tuition", "unknown", "FINAL_TUITION_NOT_GUARANTEED", "A published-rate estimate cannot guarantee the actual final tuition for a future intake.")
    elif estimate.upper_usd > profile.tuition_budget_usd:
        if estimate.reason_code == 'MAXIMUM_ONLY_TUITION_BOUND':
            add('tuition', 'unknown', 'TUITION_CEILING_ABOVE_BUDGET',
                'The conservative published-rate ceiling exceeds the budget. The actual schedule may cost less; a ceiling alone cannot prove the budget is insufficient.')
        else:
            add("tuition", "fail", "TUITION_EXCEEDS_BUDGET", "The upper bound of estimated full-program tuition exceeds the budget. Unconfirmed scholarships have not been deducted.")
    else:
        warnings = ["Estimated using the stated year's published rates. Future increases are not guaranteed; living costs are excluded and mandatory fees are listed separately."]
        if estimate.reason_code == 'MAXIMUM_ONLY_TUITION_BOUND':
            warnings.append('This is a conservative ceiling for the documented ordinary study scope, not an exact price. Additional study or a different billing arrangement needs a new check.')
        add("tuition", "pass", "TUITION_WITHIN_PUBLISHED_RATE_BUDGET", "The upper bound of estimated full-program tuition is within the budget.", warnings)

    rounds = applicable_deadline_rounds(profile, program)
    if not supported("deadline") or not rounds:
        add("deadline", "unknown", "DEADLINE_NOT_VERIFIED", "No verified deadline applies to this intake and applicant category yet.")
    elif any(round_.date > as_of for round_ in rounds):
        add("deadline", "pass", "FUTURE_APPLICABLE_DEADLINE", "At least one applicable deadline is still in the future. This does not guarantee remaining places.")
    elif any(round_.date == as_of for round_ in rounds):
        add("deadline", "unknown", "DEADLINE_TODAY_TIME_UNKNOWN", "The deadline is today, but its exact time or time zone has not been verified.")
    elif program.deadline_schedule_complete:
        add("deadline", "fail", "ALL_APPLICABLE_DEADLINES_PASSED", "All verified applicable deadline rounds have passed.")
    else:
        add("deadline", "unknown", "FINAL_DEADLINE_NOT_VERIFIED", "Known rounds have passed, but the complete applicable final deadline schedule is not verified.")

    if program.degree_required or program.eligibility_review_complete:
        degree = profile.degree
        if not supported("degree"):
            add("degree", "unknown", "DEGREE_POLICY_NOT_VERIFIED", "The applicable degree requirement is not supported by reviewed evidence.")
        elif degree is None or degree.completion == "unknown" or degree.recognition == "unknown":
            add("degree", "unknown", "MISSING_DEGREE_BACKGROUND", "Provide degree completion and recognized-bachelor/equivalency status; unknown is not assumed eligible.")
        elif degree.completion == "not_before_enrollment" or degree.recognition == "not_recognized":
            add("degree", "fail", "DEGREE_REQUIREMENT_NOT_MET", "The declared degree completion/recognition does not meet the published requirement.")
        elif program.accepted_degree_fields and degree.field == "unknown":
            add("degree", "unknown", "MISSING_DEGREE_FIELD", "The academic field is needed for the program's degree requirement.")
        elif program.accepted_degree_fields and degree.field not in program.accepted_degree_fields:
            add("degree", "fail", "DEGREE_FIELD_NOT_ACCEPTED", "The declared degree field does not meet the verified field requirement.")
        else:
            add("degree", "pass", "DEGREE_SELF_REPORTED", "The declared recognized degree meets the reviewed planning requirement. The university makes the final credential-equivalency decision.")
    if program.gre_policy != "unknown" or program.eligibility_review_complete:
        gre = profile.gre
        if not supported("gre") or program.gre_policy == "unknown":
            add("gre", "unknown", "GRE_POLICY_NOT_VERIFIED", "The program's applicable GRE rule is not verified.")
        elif program.gre_policy == "not_required":
            add("gre", "not_applicable", "GRE_NOT_REQUIRED", "The applicable official policy does not require GRE scores.")
        elif gre is None or gre.test_date is None or gre.format == "unknown":
            add("gre", "unknown", "MISSING_REQUIRED_GRE", "Provide the required GRE result, test date and test format, or leave eligibility unverified.")
        elif gre.test_date > as_of:
            add("gre", "unknown", "GRE_TEST_IN_FUTURE", "The GRE test date is later than the assessment date.")
        elif gre.format == "at_home" and program.gre_at_home_accepted is not True:
            add("gre", "unknown", "GRE_FORMAT_NOT_VERIFIED", "Acceptance of this GRE test format has not been established.")
        elif program.gre_validity_years is not None and (as_of.year, as_of.month, as_of.day) >= (gre.test_date.year + program.gre_validity_years, gre.test_date.month, gre.test_date.day):
            add("gre", "fail", "GRE_EXPIRED", "The GRE result is outside the verified validity period.")
        else:
            add("gre", "pass", "GRE_SELF_REPORTED", "The declared GRE report meets the reviewed presence/date/format rule; no unsupported score cutoff is imposed.")
    coverage_ids = evidence_ids(program, "remaining_eligibility", sources, profile)
    coverage_bound = bool(coverage_ids) and supported("degree") and supported("gre")
    if not (program.eligibility_review_complete and coverage_bound):
        add("remaining_eligibility", "unknown", "M1_PARTIAL_RULE_COVERAGE", "Degree equivalency, complete application materials, and other program conditions still require review.")
    elif "duplicate_advanced_degree" in program.field_sources and not (
            supported("duplicate_advanced_degree") and supported("application_materials")):
        add("remaining_eligibility", "unknown", "ADDITIONAL_ELIGIBILITY_EVIDENCE_INCOMPLETE",
            "The application checklist or duplicate-degree policy needs applicable official evidence.")
    elif supported("duplicate_advanced_degree") and (
            getattr(profile.degree, "prior_academic_graduate_degree", "unknown") != "none"):
        add("remaining_eligibility", "unknown", "PRIOR_ADVANCED_DEGREE_REQUIRES_REVIEW",
            "Specify previous academic graduate degrees in the profile. If you hold or expect one, confirm with the university how its duplicate-degree policy applies.")
    else:
        add("remaining_eligibility", "pass", "REMAINING_ELIGIBILITY_REVIEWED", "The planning eligibility rules are covered by reviewed sources. Required application documents are listed separately; submission and admission are not asserted.")
    status = (CheckStatus.FAIL if any(check.status == CheckStatus.FAIL for check in checks)
              else CheckStatus.UNKNOWN if any(check.status == CheckStatus.UNKNOWN for check in checks)
              else CheckStatus.PASS)
    return ConstraintReport(program_id=program.program_id, profile_version=profile.profile_version,
        as_of_date=as_of, data_mode=data_mode, checks=checks, tuition=estimate, hard_checks_status=status,
        recommendation_ready=status == CheckStatus.PASS)
