# GradMatch project conventions

## Product language

- English is the default language for every application page and future feature.
- Write UI labels, options, validation errors, explanations, warnings, progress messages, recommendation text, and agent replies in English.
- Use English for authored evidence summaries, tuition assumptions, exported assessment text, the README, and newly written project documentation.
- Preserve original source quotations and source-language evidence faithfully; provide an English summary instead of presenting a translation as a verbatim quote.
- Preserve stable field names, widget keys, numeric facts, source URLs, and retrieval dates when changing display language.
- Conversation with the user can follow the language of their messages.

## Homework branch isolation

- Develop the 50-task evaluation homework on `homework/eval-harness-50`.
- Preserve `main` at its accepted project checkpoint unless the user explicitly requests integration. The homework branch starts at `6ae734828c160b6f1fee5d3088b1b52b5f0b3ba9`.
- Keep the existing public Streamlit deployment on `main`; publish homework commits to the homework branch.
- Follow `docs/HOMEWORK_EVAL_PLAN.md`. The homework's snapshot-only Agent is a limited M4 implementation, not completion of the original live-tool milestone.
- Keep reference answers and grading rubrics out of candidate model/tool inputs. Report actual runs and retain failures; unit tests or stubs are not benchmark results.

