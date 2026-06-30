"""Validate the locked ontology WITHOUT any API call.

Checks:
  1. Graphiti's official validate_entity_types (no reserved-field collisions).
  2. Edge models don't collide with EntityEdge reserved fields.
  3. Every label/edge-name referenced in EDGE_TYPE_MAP actually exists.

Run:  uv run python scripts/validate_ontology.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from graphiti_core.edges import EntityEdge  # noqa: E402
from graphiti_core.utils.ontology_utils.entity_types_utils import (  # noqa: E402
    validate_entity_types,
)

from kg.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES  # noqa: E402


def main() -> int:
    # 1. official entity validator (raises on collision)
    validate_entity_types(ENTITY_TYPES)
    print("[1/3] entity reserved-field check : ok")

    # 2. edge reserved-field check (no official validator ships for edges)
    edge_reserved = set(EntityEdge.model_fields.keys())
    clashes = {
        name: sorted(set(m.model_fields.keys()) & edge_reserved)
        for name, m in EDGE_TYPES.items()
        if set(m.model_fields.keys()) & edge_reserved
    }
    assert not clashes, f"edge field name collisions with reserved fields: {clashes}"
    print("[2/3] edge reserved-field check   : ok")

    # 3. cross-reference EDGE_TYPE_MAP against declared types
    labels = set(ENTITY_TYPES)
    edge_names = set(EDGE_TYPES)
    unknown_labels = {
        lab for pair in EDGE_TYPE_MAP for lab in pair if lab != "Entity" and lab not in labels
    }
    unknown_edges = {e for lst in EDGE_TYPE_MAP.values() for e in lst if e not in edge_names}
    assert not unknown_labels, f"EDGE_TYPE_MAP references unknown entity labels: {unknown_labels}"
    assert not unknown_edges, f"EDGE_TYPE_MAP references unknown edge names: {unknown_edges}"
    print("[3/3] edge_type_map cross-ref     : ok")

    print(
        f"\nONTOLOGY VALID — entities={len(ENTITY_TYPES)} "
        f"edges={len(EDGE_TYPES)} map_pairs={len(EDGE_TYPE_MAP)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
