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
    r"(?:and\s+)?(?:(?:what(?:['’]s| is| are| about)|when(?:['’]s| is| are)|how (?:much is|about))\s+)?"
    r"(?:(?:the program['’]s|the|its)\s+)?(?P<topic>" + "|".join(TOPICS) + r")"
    r"(?:\s+(?:for|of|at)\s+(?P<name>.+))?",
    re.IGNORECASE,
)
GRE_TEST = r"(?:a\s+|the\s+)?gre(?:\s+scores?)?"
GRE_QUESTIONS = tuple(re.compile(r"(?:and\s+)?" + pattern, re.IGNORECASE) for pattern in (
    r"do\s+i\s+(?:need(?:\s+to\s+(?:take|submit))?|have\s+to\s+(?:take|submit))\s+"
    + GRE_TEST + r"(?:\s+to\s+apply)?(?:\s+for\s+(?P<name>.+))?",
    r"(?:does|do)\s+(?P<name>.+?)\s+(?:need|require)\s+" + GRE_TEST,
    r"(?:is\s+)?" + GRE_TEST + r"\s+(?:required|needed)(?:\s+for\s+(?P<name>.+))?",
))
PROGRAM_REFERENCES = {"it", "this program", "that program", "the program"}
UNVERIFIED_ANSWER = "I can't verify that from the available information."
QUESTION_START = re.compile(
    r"(?:(?:and|please)\s+)*(?:who|what|when|where|which|why|how|is|are|was|were|do(?!\s+not\b)|does|did|"
    r"can|could|would|will|should|has|have|tell me|show me|explain|(?:check|verify) (?:if|whether))\b",
    re.IGNORECASE,
)
ASSESSMENT_REQUEST = re.compile(
    r"(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
    r"(?:change|set|update|modify|raise|lower|increase|decrease|switch|replace|remove|clear|mark|"
    r"generate|regenerate|rerun|recommend|reassess)\b"
    r"|which (?:of the )?(?:(?:remaining|shortlisted|recommended) )?(?:candidates|programs) (?:best )?(?:fit|match)\b"
    r"|explain (?:the |my )?(?:(?:remaining|shortlisted|recommended) )?(?:candidates|programs|shortlist)"
    r"(?:[?.!]\s*(?:do not change my profile[.!]?)?)?$",
    re.IGNORECASE,
)
FUNDING_TOPIC = re.compile(
    r"(?:the\s+)?(?:financial aid|funding|scholarships?|assistantships?|stipends?|tuition waivers?)"
    r"(?:\s+(?:for|at|of)\s+.+)?",
    re.IGNORECASE,
)


def parse_catalog_question(message):
    question = " ".join(message.strip().rstrip("?.").split())
    for pattern in GRE_QUESTIONS:
        if match := pattern.fullmatch(question):
            topic = "gre"
            break
    else:
        match = QUESTION.fullmatch(question)
        if match is None:
            return None
        topic = TOPICS[match["topic"].lower()]
    name = match["name"]
    return topic, None if name and name.casefold() in PROGRAM_REFERENCES else name


def is_unhandled_question(message):
    """Keep informational chat outside the profile and recommendation workflow."""
    text = " ".join(message.split())
    if ASSESSMENT_REQUEST.match(text):
        return False
    return bool(text.endswith(("?", "？")) or QUESTION_START.match(text)
                or FUNDING_TOPIC.fullmatch(text.rstrip(".!。！")))


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
    listed = [f"- **{row.date.isoformat()}** — {row.label}" + (" (passed)" if row.date < as_of else "")
              for row in sorted(rounds, key=lambda row: row.date)]
    detail = f"The reviewed schedule for {profile.intake.term.title()} {profile.intake.year} is below.\n\n" + "\n".join(listed)
    if any(row.date == as_of for row in rounds):
        detail += "\n\nCheck the program page for today's cutoff time."
    if not program.deadline_schedule_complete:
        detail += "\n\nCheck the program page for current availability and any additional rounds."
    return detail, source_ids


def gre_answer(program, profile, sources):
    source_ids = evidence_ids(program, "gre", sources, profile)
    policies, recommendations = {}, {}
    for sid in evidence_ids(program, "directory_policies", sources, profile):
        for note in sources[sid].verified_values["directory_policies"].values():
            label, _, text = note.partition(": ")
            if label == "GRE policy":
                policies[text] = sid
            elif label == "GRE recommendation":
                recommendations[text] = sid

    if policies:
        detail = " ".join(policies)
    elif source_ids and program.gre_policy != "unknown":
        detail = "**GRE required.**" if program.gre_policy == "required" else "**GRE is not required.**"
    else:
        return None, []
    if recommendations:
        detail += " " + " ".join(recommendations)
    return detail, list(dict.fromkeys([*source_ids, *policies.values(), *recommendations.values()]))


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
