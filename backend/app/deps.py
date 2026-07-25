"""Access control for a single meeting: an edit-token instead of a login."""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .database import get_db
from .models import Meeting
from .security import verify_edit_token


async def get_meeting_for_token(
    meeting_id: int,
    x_edit_token: str | None = Header(None, alias="X-Edit-Token"),
    db: AsyncSession = Depends(get_db),
) -> Meeting:
    # select().options() always executes and applies the eager-load options;
    # db.get() would short-circuit to the identity map (skipping them) right
    # after the create endpoint's db.add()+commit() in the same session.
    result = await db.execute(
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(
            selectinload(Meeting.agenda_items),
            selectinload(Meeting.participants),
            selectinload(Meeting.segments),
        )
    )
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Toplantı bulunamadı.")
    if not x_edit_token or not verify_edit_token(x_edit_token, meeting.edit_token_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Geçersiz veya eksik düzenleme anahtarı.",
        )
    return meeting
