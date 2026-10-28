"""The agent's entry point (KG phase close, 2026-10-24): pick a template, never write Cypher.

    from kg.query import ask
    out = ask("sowing_window", {"crop": "crop:rice", "state": "state:5", "zones": ["zone:uk_tarai_bhabhar_plain"]})

`template` is one of TEMPLATES; `farm_context` is a FarmContext or a dict of its fields (an unknown field is
refused, a missing one is UNKNOWN). The result is the dict kg.query.answer returns, unchanged. Without
`driver`, a connection is opened from .env and closed again; pass `driver` to reuse one and `database` to read
a database other than the server's home database.
"""

from pydantic import ValidationError

from .answer import answer
from .context import FarmContext
from .templates import TEMPLATES


class AskError(ValueError):
    """A request the entry point refuses: an unknown template, a bad farm context, or no connection settings."""


def ask(template: str, farm_context, *, driver=None, database: str | None = None) -> dict:
    if template not in TEMPLATES:
        raise AskError("unknown template %r; pick one of: %s" % (template, ", ".join(sorted(TEMPLATES))))
    try:
        ctx = farm_context if isinstance(farm_context, FarmContext) else FarmContext.model_validate(farm_context)
    except ValidationError as e:
        raise AskError("bad farm context: %s" % "; ".join(
            "%s: %s" % (".".join(map(str, err["loc"])) or "context", err["msg"]) for err in e.errors())) from e
    if driver is not None:
        return answer(driver, template, ctx, database)
    from kg.load.db import get_driver
    try:
        own = get_driver()
    except SystemExit as e:                      # .env lacks a connection setting; raise, never exit the agent
        raise AskError(str(e)) from None
    with own:
        return answer(own, template, ctx, database)
