"""Query templates (step 14): kg.query.answer(driver, template, FarmContext) -> a structured answer.

  uv run python -m kg.query drying_target --context tests/query/fixtures/q15_grain_drying.json [--database cropbot-test]

Templates: drying_target (Q15, Q16), storage (Q17), harvest_readiness (Q12, Q14), threshold (Q8),
quality_check (Q19), varieties_for (Q1), sowing_window (Q2).
See kg.query.answer for applicability, three-valued conditions, ranking, visibility and safety.
The agent's entry point is kg.query.ask(template, farm_context) (docs/KG_HANDOVER.md).
"""

from .answer import answer
from .ask import AskError, ask
from .context import FarmContext
from .templates import TEMPLATES

__all__ = ["answer", "ask", "AskError", "FarmContext", "TEMPLATES"]
