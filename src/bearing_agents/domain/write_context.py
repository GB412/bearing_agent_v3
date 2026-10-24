from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WriterKind(StrEnum):
    AGENT = "AGENT"
    USER = "USER"
    SYSTEM = "SYSTEM"


class WriteContext(BaseModel):
    """Trusted caller capability, never part of an Agent's StatePatch or model output.

    A later UI/API must authenticate the caller before constructing USER or SYSTEM context.
    This in-process offline contract does not implement authentication.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: WriterKind = WriterKind.AGENT
    actor: str | None = None
    approved_parameter_ids: frozenset[str] = Field(default_factory=frozenset)
    approved_constraint_ids: frozenset[str] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_identity(self) -> "WriteContext":
        if self.kind != WriterKind.AGENT and (not self.actor or not self.actor.strip()):
            raise ValueError("USER/SYSTEM context requires a nonempty actor")
        if self.kind != WriterKind.USER and (
            self.approved_parameter_ids or self.approved_constraint_ids
        ):
            raise ValueError("Only USER context may approve locked domain input changes")
        return self
