"""Answer catalog questions from the same bound evidence used by screening."""

from datetime import date
import re

from gradmatch.constraints import applicable_deadline_rounds, check_constraints, evidence_ids
from gradmatch.validation import citation


TOPICS = {
    "tuition": "tuition",
    "tuition cost": "tuition",
    "deadline": "deadline",
    "application deadline": "deadline",
    "application deadlines": "deadline",
    "gre": "gre",
    "gre policy": "gre",
    "gre requirement": "gre",
}
QUESTION = re.compile(
    r"(?:(?:what(?:['’]s| is| are)|when is|how much is)\s+)?(?:the\s+)?(?P<topic>" + "|".join(TOPICS) + r")"
    r"(?:\s+(?:for|of|at)\s+(?P<name>.+))?",
    re.IGNORECASE,
)
FOLLOW_UP = re.compile(
    r"(?:what about|what(?:['’]s| is| are))\s+(?:its|the program['’]s)\s+(?P<topic>"
    + "|".join(TOPICS) + r")",
    re.IGNORECASE,
)
GRE_QUESTION = re.compile(r"does\s+(.+?)\s+require\s+(?:the\s+)?gre", re.IGNORECASE)


def parse_catalog_question(message):
    question = message.strip().rstrip("?.").rstrip()
    if match := GRE_QUESTION.fullmatch(question):
        return "gre", match[1]
    if match := FOLLOW_UP.fullmatch(question):
        return TOPICS[match["topic"].lower()], None
    if match := QUESTION.fullmatch(question):
        return TOPICS[match["topic"].lower()], match["name"]
    return None


def normalized(text):
    return " ".join(re.findall(r"[^\W_]+", text.casefold()))


def program_label(program):
    if not program.allowed_official_hosts:
        return f"{program.university} — {program.program_name}"
    return f"{program.university} — {program.degree}, {program.campus} ({program.track})"


def matches_program(program, name):
    school = normalized(program.university)
    initials = "".join(word[0] for word in school.split() if word not in {"of", "the", "at", "and", "in"})
    aliases = {normalized(program.program_id), normalized(program_label(program))}
    for university in (school, initials):
        for title in (program.program_name, program.degree):
            aliases.update(normalized(value) for value in (
                f"{university} {title}", f"{university} {title} {program.campus}",
                f"{university} {program.campus} {title}",
            ))
    return name in aliases


def resolve_program(name, programs, previous_id):
    if name:
        key = normalized(name)
        return [program for program in programs if matches_program(program, key)]
    return [program for program in programs if program.program_id == previous_id]


def usd(amount):
    return f"USD {amount:,.2f}".removesuffix(".00")


def tuition_answer(program, profile, sources, as_of):
    report = check_constraints(profile, program, sources, as_of=as_of)
    estimate = report.tuition
    lower, upper = estimate.lower_usd, estimate.upper_usd
    if lower is None and upper is None:
        return "A full-program tuition estimate is unavailable in the reviewed evidence for this route.", []
    if upper is None:
        amount = f"at least {usd(lower)}. The upper bound still needs verification"
    elif lower is None:
        amount = f"up to {usd(upper)} under the published-rate assumptions"
    elif lower == upper:
        amount = usd(upper)
    else:
        amount = f"{usd(lower)}–{usd(upper)}"
    if upper is None:
        detail = f"The reviewed {estimate.rate_year} rates give a full-program tuition minimum of {amount}."
    else:
        detail = f"Estimated full-program tuition at the {estimate.rate_year} published rates is **{amount}**."
    rate = program.tuition.unit_rate_lower
    credits = program.required_credits
    if (program.tuition.basis == "per_credit" and rate is not None and credits is not None
            and lower == upper == rate * credits):
        detail += f" The estimate uses {credits:g} credits at {usd(rate)} per credit."
    if estimate.assumptions:
        detail += " " + " ".join(estimate.assumptions)
    check = next(check for check in report.checks if check.rule_id == "tuition")
    return detail, check.source_ids


def deadline_answer(program, profile, sources, as_of):
    source_ids = evidence_ids(program, "deadline", sources, profile)
    rounds = applicable_deadline_rounds(profile, program)
    if not source_ids or not rounds:
        return None, []
    upcoming = min((row for row in rounds if row.date >= as_of), key=lambda row: row.date, default=None)
    if upcoming:
        detail = f"The next reviewed {profile.intake.key} application round is **{upcoming.date.isoformat()}** ({upcoming.label})."
    else:
        latest = max(rounds, key=lambda row: row.date)
        detail = f"The latest reviewed {profile.intake.key} round was **{latest.date.isoformat()}** ({latest.label})."
    if not program.deadline_schedule_complete:
        detail += " Check the program page for current availability and any additional rounds."
    return detail, source_ids


def gre_answer(program, profile, sources):
    source_ids = evidence_ids(program, "gre", sources, profile)
    if not source_ids or program.gre_policy == "unknown":
        return None, []
    outcome = "requires the GRE" if program.gre_policy == "required" else "does not require the GRE"
    summary = " ".join(dict.fromkeys(sources[sid].fact_summary for sid in source_ids))
    return f"The reviewed policy **{outcome}**. {summary}", source_ids


def catalog_answer(topic, name, programs, sources, profile, as_of, broad_context, previous_id):
    candidates = resolve_program(name, programs, previous_id)
    if len(candidates) > 1:
        choices = "\n".join("- " + program_label(program) for program in candidates)
        message = "Which program do you mean? Include the degree, campus or track.\n\n" + choices
        return message, None, []
    if not candidates:
        return "Enter the program name as shown in the shortlist, including its degree or campus.", None, []

    program = candidates[0]
    community_attribution = None
    if topic == "tuition":
        detail, source_ids = tuition_answer(program, profile, sources, as_of)
    elif topic == "deadline":
        detail, source_ids = deadline_answer(program, profile, sources, as_of)
    else:
        detail, source_ids = gre_answer(program, profile, sources)

    same_intake = (broad_context and profile.intake
                   and broad_context["intake"] == f"{profile.intake.term.title()} {profile.intake.year}")
    if detail is None and same_intake:
        facts = broad_context["entries"][program.program_id]["facts"]
        if topic == "deadline":
            from gradmatch.broad_catalog import screen_program
            report = check_constraints(profile, program, sources, as_of=as_of)
            screen = screen_program(profile, program, report, broad_context, as_of=as_of)
            if upcoming := screen["next_listed_round"]:
                detail = f"CS Grad lists **{upcoming['date']}** ({upcoming['label']}). Confirm the cutoff with the university."
        elif facts["reported_gre"] != "unknown":
            marker = facts["reported_gre"].replace("_", " ")
            detail = f"CS Grad reports the GRE policy as **{marker}**. Confirm the requirement with the university."
        if detail is not None:
            community_attribution = (f"[CS Grad community snapshot]({broad_context['source_url']})"
                                     f" ({broad_context['snapshot_date']})")

    if detail is None:
        detail = ("Select an intake in Applicant information to check application rounds."
                  if topic == "deadline" and profile.intake is None
                  else "The available evidence does not verify this policy for the selected intake.")

    references = [citation(sources[sid]) for sid in source_ids]
    links = list(dict.fromkeys(f"[University source]({row['url']}) (reviewed {date.fromisoformat(row['retrieved_at'][:10])})"
                              for row in references))
    if community_attribution:
        links.append(community_attribution)
    links.append(f"[Program website]({program.official_url})")
    return f"**{program_label(program)}**\n\n{detail}\n\n" + " · ".join(links), program.program_id, references
