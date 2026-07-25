"""Pydantic request/response models."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import MeetingStatus


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    agenda_items: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _strip(self):
        self.agenda_items = [a.strip() for a in self.agenda_items if a.strip()]
        self.participants = [p.strip() for p in self.participants if p.strip()]
        return self


class AgendaItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_index: int
    title: str


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_index: int
    display_name: str


class TranscriptSegmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    participant_id: int | None = None
    participant_name: str | None = None
    text: str
    created_at: datetime
    updated_at: datetime | None = None


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: MeetingStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    agenda_items: list[AgendaItemResponse] = Field(default_factory=list)
    participants: list[ParticipantResponse] = Field(default_factory=list)
    segments: list[TranscriptSegmentResponse] = Field(default_factory=list)


class MeetingCreateResponse(MeetingResponse):
    """Only returned once, by POST /api/meetings — the plaintext edit token
    is never recoverable afterward (only its hash is stored)."""

    edit_token: str


class SegmentPatch(BaseModel):
    """Manual correction of one transcript line — reassign the speaker, fix
    the text, or both. At least one field must be sent."""

    participant_id: int | None = None
    text: str | None = Field(default=None, min_length=1, max_length=4000)
    # Explicit "unassign" — participant_id=None alone can't distinguish
    # "unset" from "leave unchanged".
    clear_participant: bool = False

    @model_validator(mode="after")
    def _at_least_one(self):
        if self.participant_id is None and self.text is None and not self.clear_participant:
            raise ValueError("En az bir alan gönderilmeli.")
        return self
