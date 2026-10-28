"""A uniqueness constraint on `id` for every node label in the schema.

Run: uv run python -m kg.load.constraints
Uses only uniqueness constraints, which Neo4j Community also supports.
"""

import re

from kg.schema.vocab import Subtype

from .db import get_driver

CONCEPT_LABELS = (
    "Concept",            # shared label on every concept, for the vector index
    "Crop", "Variety", "GrowthStage", "Pest", "Disease", "Weed", "Disorder", "Symptom",
    "ActiveIngredient", "AIGroup", "Fertilizer", "OrganicInput", "Input", "Nutrient", "OperationType",
    "Country", "State", "District", "AgroClimaticZone", "Season", "LocalSeason",
    "ProductionSystem", "SoilType", "Purpose",
)
FACT_LABELS = ("Recommendation", "Step", "Condition", "ThresholdClause",
               "SourceSpan", "Source", "Label")
SUBTYPE_LABELS = tuple(s.value for s in Subtype)   # (:Recommendation:<Subtype>)

NODE_LABELS = CONCEPT_LABELS + FACT_LABELS + SUBTYPE_LABELS


def constraint_name(label: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", label).lower() + "_id_unique"


def statements() -> list[str]:
    return ["CREATE CONSTRAINT %s IF NOT EXISTS FOR (n:%s) REQUIRE n.id IS UNIQUE"
            % (constraint_name(label), label) for label in NODE_LABELS]


def ensure_constraints(driver, database=None) -> int:
    """Create any missing constraint; existing ones are left alone. Returns how many exist."""
    for stmt in statements():
        driver.execute_query(stmt, database_=database)
    records, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name WHERE name ENDS WITH '_id_unique' RETURN count(*) AS n", database_=database)
    return records[0]["n"]


if __name__ == "__main__":
    with get_driver() as drv:
        print("id uniqueness constraints in the database:", ensure_constraints(drv))
