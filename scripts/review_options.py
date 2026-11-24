#!/usr/bin/env python3
"""Normalize review skill arguments without launching agents or writing configuration."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks/scripts"))
import plugin_config


ROLES = ("lead", "reviewer", "validator")
SKILLS = ("review-code", "review-validate-fix-loop")
REVIEW_FIELDS = ("model_selection", "fallback", "strategy") + tuple(
    f"{role}_{setting}" for role in ROLES for setting in ("model", "effort")
)
# Posting is a review-code caller action, not a review choice: these fields are
# never forwarded to review phases or saved for loop resume like REVIEW_FIELDS.
POSTING_FIELDS = ("post_comments", "post_sensitive")
SENSITIVE_POLICIES = ("none", "private", "all")
POSTING_FEATURE = "review-post-comments"
NON_CATEGORY_FEATURES = ("review-auto-model-selection", POSTING_FEATURE, "review-known-issues")


class PostingConflict(ValueError):
    """Posting arguments that conflict after flags and choices are merged."""


def record_once(parser, namespace, dest, option_string):
    specified = set(getattr(namespace, "specified", ()))
    if dest in specified:
        parser.error(f"{option_string} may only be supplied once")
    specified.add(dest)
    namespace.specified = sorted(specified)


class Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        record_once(parser, namespace, self.dest, option_string)
        setattr(namespace, self.dest, values)


class OnceFlag(argparse.Action):
    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest, nargs=0, default=False, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        record_once(parser, namespace, self.dest, option_string)
        setattr(namespace, self.dest, True)


def nonempty(value):
    if not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
        raise argparse.ArgumentTypeError("expected a nonempty value without surrounding whitespace or controls")
    return value


def positive(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return number


def parser_for(skill):
    parser = argparse.ArgumentParser(
        prog=f"review_options.py {skill}", allow_abbrev=False,
        description="Skill options. Defaults run without a setup prompt. Model names are host-specific.",
        epilog="This helper does not select models, grant permission, launch agents, or modify settings.",
    )
    parser.add_argument("target", nargs="*", help="scope; omitted means active PR or branch/local changes")
    parser.add_argument("--model-selection", choices=("auto", "configured"), default="auto",
                        action=Once, help="policy for unspecified roles (default: auto, subject to host authority)")
    parser.add_argument("--fallback", choices=("configured", "fail"), action=Once,
                        help="launch fallback (default: fail for explicit overrides, configured otherwise)")
    parser.add_argument("--strategy", choices=("auto", "sweep-first", "specialists"), default="auto",
                        action=Once, help="review order; auto uses isolated specialists, sweep-first changes order only")
    for role in ROLES:
        parser.add_argument(f"--{role}-model", type=nonempty, action=Once, metavar="MODEL",
                            help=f"explicit {role} model; omitted roles use the selection policy")
        parser.add_argument(f"--{role}-effort", type=nonempty, action=Once, metavar="LEVEL",
                            help=f"explicit {role} effort; validate against the native host/model")
    if skill == "review-code":
        parser.add_argument("--post-comments", action=OnceFlag,
                            help="publish reportable findings as one COMMENT review on the reviewed PR")
        parser.add_argument("--post-sensitive", choices=SENSITIVE_POLICIES, default="private", action=Once,
                            help="sensitive findings: none, private (default: on public repositories, only those "
                                 "this pull request introduces), or all")
    if skill == "review-validate-fix-loop":
        parser.add_argument("--max-loops", type=positive, default=3, action=Once,
                            help="outer review limit (default: 3)")
        parser.add_argument("--max-fix-cycles", type=positive, default=3, action=Once,
                            help="correction limit per outer loop (default: 3)")
        parser.add_argument("--resume", type=nonempty, action=Once, metavar="LEDGER",
                            help="resume saved scope and limits, preserving unspecified review choices")
    return parser


def parse_options(skill, argv):
    parser = parser_for(skill)
    args = parser.parse_intermixed_args(argv)
    specified = getattr(args, "specified", [])
    if getattr(args, "resume", None) and (
        args.target or {"max_loops", "max_fix_cycles"}.intersection(specified)
    ):
        parser.error("--resume reuses the saved target and limits; omit target and limit arguments")
    options = {
        "skill": skill, "target": args.target,
        "specified": specified, "resume": getattr(args, "resume", None),
        "max_loops": None if getattr(args, "resume", None) else getattr(args, "max_loops", None),
        "max_fix_cycles": None if getattr(args, "resume", None) else getattr(args, "max_fix_cycles", None),
        "option_sources": {name: "invocation" if name in specified else "default"
                           for name in REVIEW_FIELDS + posting_fields(skill)},
    }
    options.update({name: getattr(args, name) for name in posting_fields(skill)})
    return apply_values(options, {name: getattr(args, name) for name in REVIEW_FIELDS})


def posting_fields(skill):
    return POSTING_FIELDS if skill == "review-code" else ()


def validate_posting_choice(name, value):
    if name == "post_comments" and type(value) is not bool:
        raise ValueError("expected true or false for post_comments")
    if name == "post_sensitive" and value not in SENSITIVE_POLICIES:
        raise ValueError(f"expected one of {', '.join(SENSITIVE_POLICIES)} for post_sensitive")


def apply_values(options, values):
    result = {**options, **{name: values[name] for name in ("model_selection", "fallback", "strategy")}}
    result["effective_strategy"] = "specialists" if values["strategy"] == "auto" else values["strategy"]
    result["roles"] = {}
    for role in ROLES:
        model, effort = values[f"{role}_model"], values[f"{role}_effort"]
        result["roles"][role] = {
            "model": model, "effort": effort,
            "fallback": values["fallback"] or ("fail" if model or effort else "configured"),
        }
    return result


def review_values(options):
    return {
        **{name: options[name] for name in ("model_selection", "fallback", "strategy")},
        **{f"{role}_{setting}": options["roles"][role][setting]
           for role in ROLES for setting in ("model", "effort")},
    }


def validate_values(skill, values):
    argv = []
    for name, value in values.items():
        if name not in REVIEW_FIELDS:
            raise ValueError(f"unknown review option in context: {name}")
        if value is None and name not in ("model_selection", "strategy"):
            continue
        if not isinstance(value, str):
            raise ValueError(f"expected a string for {name}")
        argv.append(f"--{name.replace('_', '-')}={value}")
    return review_values(parse_options(skill, argv))


def merge_context(options, context):
    if not isinstance(context, dict) or set(context) - {"saved", "choices"}:
        raise ValueError("context must contain only saved options and/or resolved user choices")
    if options["resume"] and "saved" not in context:
        raise ValueError("resume needs --context with saved review options, or saved: null for an older run")
    values, sources = review_values(options), dict(options["option_sources"])
    posting = {name: options[name] for name in posting_fields(options["skill"])}
    saved = context.get("saved")
    if saved is not None:
        if not options["resume"] or not isinstance(saved, dict) or saved.get("skill") != options["skill"]:
            raise ValueError("saved review options require a matching resumed skill")
        try:
            values = validate_values(options["skill"], review_values(saved))
            saved_sources = saved.get("option_sources", {})
            sources = {name: saved_sources.get(name, "saved request; authority unverified") for name in REVIEW_FIELDS}
            if any(not isinstance(source, str) or not source.strip() for source in sources.values()):
                raise ValueError("saved option sources must be nonempty strings")
        except (KeyError, TypeError, AttributeError):
            raise ValueError("saved review options are incomplete or malformed") from None
    choices = context.get("choices", {})
    if not isinstance(choices, dict):
        raise ValueError("choices must map review option names to value/source objects")
    for name, choice in choices.items():
        if not isinstance(choice, dict) or set(choice) != {"value", "source"}:
            raise ValueError(f"choice {name} needs value and source")
        if not isinstance(choice["source"], str):
            raise ValueError(f"choice {name} source must be a nonempty string")
        nonempty(choice["source"])
        if name in posting_fields(options["skill"]):
            validate_posting_choice(name, choice["value"])
            posting[name] = choice["value"]
        else:
            validate_values(options["skill"], {name: choice["value"]})
            values[name] = choice["value"]
        sources[name] = choice["source"]
    for name in set(options["specified"]).intersection(REVIEW_FIELDS):
        values[name], sources[name] = review_values(options)[name], "invocation"
    for name in set(options["specified"]).intersection(posting):
        posting[name], sources[name] = options[name], "invocation"
    if posting and not posting["post_comments"] and sources["post_sensitive"] != "default":
        raise PostingConflict("--post-sensitive needs --post-comments or an explicit post_comments choice")
    limitations = ["Prior review options unavailable; using defaults and current explicit choices."] if (
        options["resume"] and saved is None
    ) else []
    return apply_values({**options, **posting, "option_sources": sources,
                         "option_limitations": limitations}, values)


def read_configuration(skill):
    project = str(Path.cwd())
    catalog = plugin_config.defaults()
    disabled = plugin_config.synchronize(project, catalog=catalog, persist=False, strict=True)
    return {
        "project": project,
        "skill_enabled": f"skill:{skill}" in catalog and f"skill:{skill}" not in disabled,
        "auto_selection_enabled": (
            "review-auto-model-selection" in catalog and "review-auto-model-selection" not in disabled
        ),
        "post_comments_enabled": POSTING_FEATURE in catalog and POSTING_FEATURE not in disabled,
        "known_issues_enabled": "review-known-issues" in catalog and "review-known-issues" not in disabled,
        "review_features": {name: name not in disabled for name in catalog
                            if name.startswith("review-") and name not in NON_CATEGORY_FEATURES},
    }


def main(argv=None):
    control = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    control.add_argument("--context", type=Path, help="private JSON with saved options/resolved user choices")
    control.add_argument("skill", choices=SKILLS)
    control.add_argument("arguments", nargs=argparse.REMAINDER)
    args = control.parse_args(argv)
    options = parse_options(args.skill, args.arguments)
    try:
        context = json.loads(args.context.read_text()) if args.context else {}
        options = merge_context(options, context)
    except PostingConflict as error:
        print(f"review-options: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, argparse.ArgumentTypeError) as error:
        print(f"review-options: invalid option context: {error}", file=sys.stderr)
        return 2
    try:
        configuration = read_configuration(options["skill"])
    except (OSError, ValueError, TypeError) as error:
        print(f"review-options: configuration unavailable: {error}. "
              "Continue authorized work without this skill; do not infer model override permission.",
              file=sys.stderr)
        return 2
    options["configuration"] = configuration
    options["effective_model_selection"] = (
        options["model_selection"] if configuration["auto_selection_enabled"] else "configured"
    )
    if "post_comments" in options:
        options["effective_post_comments"] = (
            options["post_comments"] and configuration["post_comments_enabled"]
        )
        if options["post_comments"] and not configuration["post_comments_enabled"]:
            options["option_limitations"] = options["option_limitations"] + [
                f"Posting was requested but {POSTING_FEATURE} is disabled; the review runs without posting."
            ]
    print(json.dumps(options, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
