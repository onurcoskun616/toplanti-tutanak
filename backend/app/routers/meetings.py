"""Live meeting-minutes ("toplantı tutanağı") — Faz 1.

ASR (faster-whisper, Turkish) turns short recorded audio chunks into text; the
phone app tags each chunk with whichever participant is manually selected as
"currently speaking" (no diarization/voice-matching yet — that's Faz 2), and
any transcript line can be re-tagged or edited afterward. Faz 3 (LLM
compilation, signature/PDF) is not built here either — a meeting simply ends
with a flat, read-only transcript.

There are no user accounts: each meeting is protected by a per-meeting edit
token (see security.py/deps.py) handed to the client once, at creation. Raw
audio is never persisted — it's transcribed and discarded immediately.
"""
import asyncio
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .. import asr
from ..database import get_db
from ..deps import get_meeting_for_token
from ..models import Meeting, MeetingAgendaItem, MeetingParticipant, MeetingStatus, MeetingTranscriptSegment
from ..schemas import (
    MeetingCreate,
    MeetingCreateResponse,
    MeetingResponse,
    SegmentPatch,
    TranscriptSegmentResponse,
)
from ..security import generate_edit_token, hash_edit_token

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

# A single chunk shouldn't run long — callers record ~6-8s clips. This just
# guards against an oversized/misbehaving upload, not against normal use.
MAX_AUDIO_BYTES = 15 * 1024 * 1024


def _segment_response(seg: MeetingTranscriptSegment, name_by_id: dict[int, str]) -> TranscriptSegmentResponse:
    return TranscriptSegmentResponse(
        id=seg.id,
        participant_id=seg.participant_id,
        participant_name=name_by_id.get(seg.participant_id) if seg.participant_id else None,
        text=seg.text,
        created_at=seg.created_at,
        updated_at=seg.updated_at,
    )


def _meeting_response(meeting: Meeting) -> MeetingResponse:
    name_by_id = {p.id: p.display_name for p in meeting.participants}
    return MeetingResponse(
        id=meeting.id,
        title=meeting.title,
        status=meeting.status,
        started_at=meeting.started_at,
        ended_at=meeting.ended_at,
        created_at=meeting.created_at,
        agenda_items=meeting.agenda_items,
        participants=meeting.participants,
        segments=[_segment_response(s, name_by_id) for s in meeting.segments],
    )


@router.post("", response_model=MeetingCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_meeting(payload: MeetingCreate, db: AsyncSession = Depends(get_db)):
    token = generate_edit_token()
    meeting = Meeting(title=payload.title, edit_token_hash=hash_edit_token(token))
    db.add(meeting)
    await db.flush()

    for i, title in enumerate(payload.agenda_items):
        db.add(MeetingAgendaItem(meeting_id=meeting.id, order_index=i, title=title))
    for i, name in enumerate(payload.participants):
        db.add(MeetingParticipant(meeting_id=meeting.id, order_index=i, display_name=name))

    await db.commit()

    # Re-fetch through the token dependency's eager-loading query (db.get()
    # would short-circuit to the identity map and skip the eager-load options
    # here, right after add()+commit() in the same session).
    meeting = await get_meeting_for_token(meeting.id, token, db)
    return MeetingCreateResponse(**_meeting_response(meeting).model_dump(), edit_token=token)


@router.get("/{meeting_id}", response_model=MeetingResponse)
async def get_meeting(meeting: Meeting = Depends(get_meeting_for_token)):
    return _meeting_response(meeting)


@router.post("/{meeting_id}/start", response_model=MeetingResponse)
async def start_meeting(
    meeting: Meeting = Depends(get_meeting_for_token),
    db: AsyncSession = Depends(get_db),
):
    if meeting.status != MeetingStatus.setup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Toplantı zaten başlatılmış.")
    meeting.status = MeetingStatus.live
    meeting.started_at = datetime.now(timezone.utc)
    await db.commit()
    return _meeting_response(meeting)


@router.post("/{meeting_id}/audio-chunk", response_model=TranscriptSegmentResponse)
async def upload_audio_chunk(
    audio: UploadFile = File(...),
    participant_id: int | None = Form(None),
    meeting: Meeting = Depends(get_meeting_for_token),
    db: AsyncSession = Depends(get_db),
):
    if not asr.asr_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ASR (konuşma tanıma) motoru bu sunucuda kurulu değil.",
        )
    if meeting.status != MeetingStatus.live:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Toplantı canlı kayıtta değil.")
    if participant_id is not None and not any(p.id == participant_id for p in meeting.participants):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Katılımcı bulunamadı.")

    audio_bytes = await audio.read()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ses parçası çok büyük.")

    # faster-whisper is blocking/CPU-bound — keep it off the event loop.
    # Model loading (and its first-use Hugging Face download) can fail at
    # runtime even when the package imported fine — surface that as a 503,
    # same as "not installed", rather than a raw 500.
    try:
        text = await asyncio.to_thread(asr.transcribe, audio_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"ASR motoru şu anda kullanılamıyor: {exc}",
        ) from exc
    if not text:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    segment = MeetingTranscriptSegment(meeting_id=meeting.id, participant_id=participant_id, text=text)
    db.add(segment)
    await db.commit()

    name_by_id = {p.id: p.display_name for p in meeting.participants}
    return _segment_response(segment, name_by_id)


@router.get("/{meeting_id}/segments", response_model=list[TranscriptSegmentResponse])
async def list_new_segments(
    after_id: int = Query(0, ge=0),
    meeting: Meeting = Depends(get_meeting_for_token),
):
    name_by_id = {p.id: p.display_name for p in meeting.participants}
    return [_segment_response(s, name_by_id) for s in meeting.segments if s.id > after_id]


@router.patch("/{meeting_id}/segments/{segment_id}", response_model=TranscriptSegmentResponse)
async def patch_segment(
    segment_id: int,
    payload: SegmentPatch,
    meeting: Meeting = Depends(get_meeting_for_token),
    db: AsyncSession = Depends(get_db),
):
    segment = next((s for s in meeting.segments if s.id == segment_id), None)
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Satır bulunamadı.")

    if payload.clear_participant:
        segment.participant_id = None
    elif payload.participant_id is not None:
        if not any(p.id == payload.participant_id for p in meeting.participants):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Katılımcı bulunamadı.")
        segment.participant_id = payload.participant_id
    if payload.text is not None:
        segment.text = payload.text.strip()
    segment.updated_at = datetime.now(timezone.utc)

    await db.commit()
    name_by_id = {p.id: p.display_name for p in meeting.participants}
    return _segment_response(segment, name_by_id)


@router.post("/{meeting_id}/end", response_model=MeetingResponse)
async def end_meeting(
    meeting: Meeting = Depends(get_meeting_for_token),
    db: AsyncSession = Depends(get_db),
):
    if meeting.status != MeetingStatus.live:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Toplantı canlı kayıtta değil.")
    meeting.status = MeetingStatus.ended
    meeting.ended_at = datetime.now(timezone.utc)
    await db.commit()
    return _meeting_response(meeting)
