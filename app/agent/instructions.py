"""agent / instructions responsibilities."""
from __future__ import annotations

from app.agent import prechecks, prompts, runner, schemas, submission
from app.agent.tools import scenes

from typing import Any
import ast
import hashlib
import inspect
import json


INSTRUCTION_BUILDERS = (
    "_initial_scene_message", "_precheck_message", "_true_account_message",
    "_moment_message", "_sequence_message", "_premise_probe",
    "_verify_submission", "_search_progress_hint", "_synthesize", "run_agent",
)


INSTRUCTION_TEMPLATES = (
    "hyde_system", "grammar_system", "query_expansion_system",
    "scene_moment_system", "scene_select_system",
)


def instruction_manifest() -> dict[str, Any]:
    """Current instructions, tool contracts, and inline message templates.

    Helper literals conservatively include formatting and data keys, so edits to
    message construction cannot silently evade the released instruction boundary.
    Corpus overrides are recorded independently through prompt/profile identities.
    """
    from app.prompt_templates import PROMPT_TEMPLATES
    builders = {
        "_initial_scene_message": scenes._initial_scene_message,
        "_precheck_message": prechecks._precheck_message,
        "_true_account_message": prechecks._true_account_message,
        "_moment_message": prechecks._moment_message,
        "_sequence_message": prechecks._sequence_message,
        "_premise_probe": prechecks._premise_probe,
        "_verify_submission": submission._verify_submission,
        "_search_progress_hint": submission._search_progress_hint,
        "_synthesize": submission._synthesize,
        "run_agent": runner.run_agent,
    }
    functions = {
        name: next(node for node in ast.parse(inspect.getsource(builders[name])).body
                   if isinstance(node, ast.FunctionDef))
        for name in INSTRUCTION_BUILDERS
    }
    return {
        "format": 1,
        "system": prompts.SYSTEM_PROMPT,
        "synthesis": prompts._SYNTHESIS_SYSTEM,
        "tools": schemas._tool_specs(),
        "templates": {name: PROMPT_TEMPLATES[name] for name in INSTRUCTION_TEMPLATES},
        "messages": {
            name: sorted(node.value for node in ast.walk(functions[name])
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and not (isinstance(functions[name].body[0], ast.Expr)
                            and node is functions[name].body[0].value))
            for name in INSTRUCTION_BUILDERS
        },
    }


def instruction_fingerprint() -> str:
    return hashlib.sha256(json.dumps(instruction_manifest(), ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()
