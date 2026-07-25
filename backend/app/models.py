"""ORM models — live meeting minutes (Faz 1: ASR + manual speaker tagging)."""
import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MeetingStatus(str, enum.Enum):
    setup = "setup"  # being configured (title/agenda/participants), not yet recording
    live = "live"     # recording — audio chunks are accepted and transcribed
    ended = "ended"   # recording stopped; transcript is final (read-only)


class Meeting(Base):
    """A live meeting-minutes session. No user accounts exist in this
    standalone app — access is instead controlled by a per-meeting edit
    token (see security.py/deps.py): only its sha256 hash is stored here,
    the plaintext is returned once, at creation.

    Raw audio is never persisted — voice is biometric data under KVKK, so
    only the ASR-transcribed text is kept (see MeetingTranscriptSegment).
    """

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[MeetingStatus] = mapped_column(
        Enum(MeetingStatus, name="meeting_status"),
        default=MeetingStatus.setup,
        nullable=False,
    )
    edit_token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )

    agenda_items: Mapped[list["MeetingAgendaItem"]] = relationship(
        back_populates="meeting",
        order_by="MeetingAgendaItem.order_index",
        cascade="all, delete-orphan",
    )
    participants: Mapped[list["MeetingParticipant"]] = relationship(
        back_populates="meeting",
        order_by="MeetingParticipant.order_index",
        cascade="all, delete-orphan",
    )
    segments: Mapped[list["MeetingTranscriptSegment"]] = relationship(
        back_populates="meeting",
        order_by="MeetingTranscriptSegment.id",
        cascade="all, delete-orphan",
    )


class MeetingAgendaItem(Base):
    __tablename__ = "meeting_agenda_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    meeting: Mapped["Meeting"] = relationship(back_populates="agenda_items")


class MeetingParticipant(Base):
    """A participant identified by name only — free text entered at setup,
    not a system account."""

    __tablename__ = "meeting_participants"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)

    meeting: Mapped["Meeting"] = relationship(back_populates="participants")


class MeetingTranscriptSegment(Base):
    """One ASR-transcribed line. ``participant_id`` is NULL until manually
    tagged (Faz 1 has no diarization — the phone app selects "who's talking
    now" before/while they speak, or a line is tagged after the fact)."""

    __tablename__ = "meeting_transcript_segments"

    id: Mapped[int] = mapped_column(primary_key=True)
    meeting_id: Mapped[int] = mapped_column(
        ForeignKey("meetings.id", ondelete="CASCADE"), index=True, nullable=False
    )
    participant_id: Mapped[int | None] = mapped_column(
        ForeignKey("meeting_participants.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    meeting: Mapped["Meeting"] = relationship(back_populates="segments")
    participant: Mapped["MeetingParticipant | None"] = relationship()
