"""Edge (fact) type definitions for the personal knowledge/capability graph.

Project's LOCKED ontology (7 edge types), ported from src/kg/ontology.py into
the vendored Graphiti MCP server's model registry. config.yaml references these
by ``name`` (matching a key in EDGE_TYPES → rich model is used) and constrains
which pair of entity types each edge may connect via ``edge_type_map``.

Attributes declared on an edge model are extracted by the LLM and stored on the
edge. The ``confidence`` fields are the promotion signal (§按风险晋升): the
extractor's 0-1 confidence that a capability claim is real, not aspirational.
Only populate attributes from information present in the episode.

Fact/temporal/provenance fields are Graphiti-managed (an edge's ``episodes``
already records which episode a fact came from), so we do NOT redefine them.
"""

from pydantic import BaseModel, Field


class HAS_SKILL(BaseModel):
    """The person possesses/can perform this skill."""

    proficiency: str | None = Field(default=None, description="Level if stated.")
    confidence: float | None = Field(
        default=None,
        description="0-1 extractor confidence that this ability is real, not aspirational.",
    )


class UNDERSTANDS(BaseModel):
    """The person comprehends this concept/knowledge area (knows about it)."""

    depth: str | None = Field(default=None, description="Depth if stated.")
    confidence: float | None = Field(default=None, description="0-1 extractor confidence.")


class USES(BaseModel):
    """The person (or a project) uses this technology."""

    confidence: float | None = Field(default=None, description="0-1 extractor confidence.")


class DEMONSTRATES(BaseModel):
    """A project or experience provides EVIDENCE for a skill or concept. This is
    the evidence edge that backs a capability claim — the core of job-seeking
    credibility."""

    confidence: float | None = Field(default=None, description="0-1 extractor confidence.")


class BUILT_WITH(BaseModel):
    """A project was built with this technology."""

    ...


class PART_OF(BaseModel):
    """A project belongs to an experience or organization."""

    ...


class RELATES_TO(BaseModel):
    """A generic association between two technologies/concepts, used to weave the
    knowledge network (e.g. 'SolidJS' relates_to 'reactive programming')."""

    ...


EDGE_TYPES: dict[str, type[BaseModel]] = {
    'HAS_SKILL': HAS_SKILL,
    'UNDERSTANDS': UNDERSTANDS,
    'USES': USES,
    'DEMONSTRATES': DEMONSTRATES,
    'BUILT_WITH': BUILT_WITH,
    'PART_OF': PART_OF,
    'RELATES_TO': RELATES_TO,
}
