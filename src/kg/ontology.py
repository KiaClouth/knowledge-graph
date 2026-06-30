"""Locked ontology for the personal knowledge/capability graph.

Design rules learned from graphiti-core 0.29.2 source (verified, not guessed):

1. Custom entity/edge types are Pydantic models whose fields hold ONLY *extra*
   attributes. Field names MUST NOT collide with Graphiti-managed fields, or
   `validate_entity_types` raises EntityTypeValidationError:
     EntityNode reserved: attributes, created_at, group_id, labels, name,
                          name_embedding, summary, uuid
     EntityEdge reserved: attributes, created_at, episodes, expired_at, fact,
                          fact_embedding, group_id, invalid_at, name,
                          reference_time, source_node_uuid, target_node_uuid,
                          uuid, valid_at
   => We do NOT redefine name/summary/temporal/provenance; Graphiti owns them.
   => `episodes` (on edges) already records which episode a fact came from, so
      provenance is built in — we don't duplicate it.

2. Each model's DOCSTRING is sent to the LLM as the type description and steers
   extraction. Docstrings here are written as extraction guidance, not prose.

3. edge_type_map maps (SourceLabel, TargetLabel) -> [edge type names].
   ('Entity', 'Entity') is a WILDCARD signature applying to any node pair.
   Unmapped pairs fall back to the wildcard rather than being hard-rejected, so
   "locked" constrains the *vocabulary*, not off-ontology pairs absolutely.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Entity types  (the LABEL is the dict key passed to add_episode; the class
# fields are extra attributes only)
# ---------------------------------------------------------------------------


class Person(BaseModel):
    """A human. Primarily the graph owner, but may include collaborators,
    managers, or named people encountered in projects/experiences."""

    role: str | None = Field(None, description="Primary role/title, e.g. 'frontend engineer'.")


class Skill(BaseModel):
    """An ABILITY the person can actively DO/perform — a practiced, demonstrable
    capability (e.g. 'build SolidJS UIs', 'design state machines'). Use this for
    'can do', NOT for topics merely understood. If it's knowledge/understanding
    without doing, use Concept instead."""

    proficiency: str | None = Field(
        None, description="Self-or-evidenced level: e.g. beginner/intermediate/advanced/expert."
    )


class Concept(BaseModel):
    """A KNOWLEDGE area the person UNDERSTANDS — a topic, theory, or domain they
    comprehend but do not necessarily perform as a hands-on skill (e.g.
    'distributed systems theory', 'type theory'). Use for 'knows about / has
    range in', as opposed to Skill ('can do')."""

    depth: str | None = Field(
        None, description="Depth of understanding: e.g. familiar/working/deep."
    )


class Technology(BaseModel):
    """A concrete tool, language, framework, library, platform, or product
    (e.g. 'TypeScript', 'SolidJS', 'Kùzu', 'PostgreSQL'). Nouns you can name and
    version, not abilities or topics."""

    category: str | None = Field(
        None, description="e.g. language/framework/library/database/platform/tool."
    )


class Project(BaseModel):
    """A concrete piece of work or product the person built or contributed to
    (e.g. an app, a library, a system). Has identity and an outcome."""

    status: str | None = Field(None, description="e.g. active/shipped/archived/prototype.")
    url: str | None = Field(None, description="Repo or live URL if mentioned.")


class Experience(BaseModel):
    """A role, job, engagement, or sustained body of work over a time span
    (e.g. 'Frontend engineer at Acme', 'freelance period'). Contrast with
    Project, which is a specific built artifact."""

    organization: str | None = Field(None, description="Org name if applicable.")


class Organization(BaseModel):
    """A company, team, school, or institution (employer, client, etc.)."""

    kind: str | None = Field(None, description="e.g. company/team/school/client.")


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": Person,
    "Skill": Skill,
    "Concept": Concept,
    "Technology": Technology,
    "Project": Project,
    "Experience": Experience,
    "Organization": Organization,
}


# ---------------------------------------------------------------------------
# Edge types  (fields = extra attributes only; the relationship's `fact`,
# temporal validity, and `episodes`/provenance are Graphiti-managed)
# ---------------------------------------------------------------------------


class HAS_SKILL(BaseModel):
    """The person possesses/can perform this skill."""

    proficiency: str | None = Field(None, description="Level if stated.")
    confidence: float | None = Field(
        None, description="0-1 extractor confidence that this ability is real, not aspirational."
    )


class UNDERSTANDS(BaseModel):
    """The person comprehends this concept/knowledge area (knows about it)."""

    depth: str | None = Field(None, description="Depth if stated.")
    confidence: float | None = Field(None, description="0-1 extractor confidence.")


class USES(BaseModel):
    """The person (or a project) uses this technology."""

    confidence: float | None = Field(None, description="0-1 extractor confidence.")


class DEMONSTRATES(BaseModel):
    """A project or experience provides EVIDENCE for a skill or concept. This is
    the evidence edge that backs a capability claim — the core of job-seeking
    credibility."""

    confidence: float | None = Field(None, description="0-1 extractor confidence.")


class BUILT_WITH(BaseModel):
    """A project was built with this technology."""


class PART_OF(BaseModel):
    """A project belongs to an experience or organization."""


class RELATES_TO(BaseModel):
    """A generic association between two technologies/concepts, used to weave the
    knowledge network (e.g. 'SolidJS' relates_to 'reactive programming')."""


EDGE_TYPES: dict[str, type[BaseModel]] = {
    "HAS_SKILL": HAS_SKILL,
    "UNDERSTANDS": UNDERSTANDS,
    "USES": USES,
    "DEMONSTRATES": DEMONSTRATES,
    "BUILT_WITH": BUILT_WITH,
    "PART_OF": PART_OF,
    "RELATES_TO": RELATES_TO,
}


# (SourceLabel, TargetLabel) -> allowed edge type names.
# Constrains which relationships the extractor may draw between which node kinds.
EDGE_TYPE_MAP: dict[tuple[str, str], list[str]] = {
    ("Person", "Skill"): ["HAS_SKILL"],
    ("Person", "Concept"): ["UNDERSTANDS"],
    ("Person", "Technology"): ["USES"],
    ("Person", "Project"): ["DEMONSTRATES"],
    ("Person", "Experience"): ["DEMONSTRATES"],
    ("Project", "Technology"): ["USES", "BUILT_WITH"],
    ("Project", "Skill"): ["DEMONSTRATES"],
    ("Project", "Concept"): ["DEMONSTRATES"],
    ("Experience", "Skill"): ["DEMONSTRATES"],
    ("Experience", "Concept"): ["DEMONSTRATES"],
    ("Project", "Experience"): ["PART_OF"],
    ("Project", "Organization"): ["PART_OF"],
    ("Experience", "Organization"): ["PART_OF"],
    ("Technology", "Concept"): ["RELATES_TO"],
    ("Concept", "Concept"): ["RELATES_TO"],
    ("Technology", "Technology"): ["RELATES_TO"],
}
