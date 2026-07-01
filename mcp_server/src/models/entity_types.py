"""Entity type definitions for the personal knowledge/capability graph.

This is the project's LOCKED ontology (7 entity types), ported from
src/kg/ontology.py into the vendored Graphiti MCP server's model registry.
config.yaml references these by ``name``; because each name matches a model
registered in ENTITY_TYPES below, graphiti-core uses the rich Pydantic model
(its docstring steers extraction, its fields become extracted attributes).

Design rules (verified against graphiti-core 0.29.2 source, not guessed):
- A model's fields hold ONLY *extra* attributes. Field names MUST NOT collide
  with Graphiti-managed EntityNode fields (attributes, created_at, group_id,
  labels, name, name_embedding, summary, uuid), or validate_entity_types raises.
- Each model's DOCSTRING is sent to the LLM as the type description and steers
  extraction; docstrings here are written as extraction guidance, not prose.

Note on User/Assistant: graphiti-core has built-in speaker concepts for
EpisodeType.message input. In conversational form ("User: 我用X做了Y"), the
speaker "User" is extracted and classified as Person below — that is the natural
graph-owner anchor (migration probe: message input yields 1 Person + capability
edges natively, so no separate owner injection is needed).
"""

from pydantic import BaseModel, Field


class Person(BaseModel):
    """A human. Primarily the graph owner (the "User" speaker in conversational
    input), but may include collaborators, managers, or named people encountered
    in projects/experiences."""

    role: str | None = Field(
        default=None, description="Primary role/title, e.g. 'frontend engineer'."
    )


class Skill(BaseModel):
    """An ABILITY the person can actively DO/perform — a practiced, demonstrable
    capability (e.g. 'build SolidJS UIs', 'design state machines'). Use this for
    'can do', NOT for topics merely understood. If it's knowledge/understanding
    without doing, use Concept instead."""

    proficiency: str | None = Field(
        default=None,
        description="Self-or-evidenced level: e.g. beginner/intermediate/advanced/expert.",
    )


class Concept(BaseModel):
    """A KNOWLEDGE area the person UNDERSTANDS — a topic, theory, or domain they
    comprehend but do not necessarily perform as a hands-on skill (e.g.
    'distributed systems theory', 'type theory'). Use for 'knows about / has
    range in', as opposed to Skill ('can do')."""

    depth: str | None = Field(
        default=None, description="Depth of understanding: e.g. familiar/working/deep."
    )


class Technology(BaseModel):
    """A concrete tool, language, framework, library, platform, or product
    (e.g. 'TypeScript', 'SolidJS', 'Neo4j', 'PostgreSQL'). Nouns you can name and
    version, not abilities or topics."""

    category: str | None = Field(
        default=None, description="e.g. language/framework/library/database/platform/tool."
    )


class Project(BaseModel):
    """A concrete piece of work or product the person built or contributed to
    (e.g. an app, a library, a system). Has identity and an outcome."""

    status: str | None = Field(default=None, description="e.g. active/shipped/archived/prototype.")
    url: str | None = Field(default=None, description="Repo or live URL if mentioned.")


class Experience(BaseModel):
    """A role, job, engagement, or sustained body of work over a time span
    (e.g. 'Frontend engineer at Acme', 'freelance period'). Contrast with
    Project, which is a specific built artifact."""

    organization: str | None = Field(default=None, description="Org name if applicable.")


class Organization(BaseModel):
    """A company, team, school, or institution (employer, client, etc.)."""

    kind: str | None = Field(default=None, description="e.g. company/team/school/client.")


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    'Person': Person,
    'Skill': Skill,
    'Concept': Concept,
    'Technology': Technology,
    'Project': Project,
    'Experience': Experience,
    'Organization': Organization,
}
