from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from core.library_manager import library_manager
from models.library import LibraryItem, LibraryResponse

router = APIRouter(prefix="/api/v1/library", tags=["Library"])


class StatusUpdateRequest(BaseModel):
    status: str


class ProgressUpdateRequest(BaseModel):
    season: Optional[int] = None
    episode: Optional[int] = None
    progress_percent: Optional[int] = None
    playback_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    status: Optional[str] = None


class BulkLibraryRequest(BaseModel):
    items: List[LibraryItem]


@router.get("", response_model=LibraryResponse)
async def get_library_items(
    status: Optional[str] = Query(None, description="Optional status filter: watching, plan_to_watch, completed, on_hold, dropped"),
):
    """
    Fetches all bookmarked titles in user's library with counts per status category.
    """
    return await library_manager.get_items(status=status)


@router.get("/{item_id}", response_model=LibraryItem)
async def get_library_item(item_id: str):
    """
    Fetches a specific bookmarked title from the library.
    """
    item = await library_manager.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Title not found in library")
    return item


@router.post("", response_model=LibraryItem)
async def upsert_library_item(item: LibraryItem):
    """
    Adds a title to the user's library or updates an existing bookmark.
    """
    return await library_manager.upsert_item(item)


@router.post("/bulk")
async def bulk_upsert_library_items(req: BulkLibraryRequest):
    """
    Restores or imports multiple titles into user's library from JSON/CSV backup.
    """
    imported = await library_manager.bulk_upsert_items(req.items)
    return {"status": "success", "imported": imported, "message": f"Successfully imported {imported} titles into Library"}


@router.patch("/{item_id}/status", response_model=LibraryItem)
async def update_library_status(item_id: str, req: StatusUpdateRequest):
    """
    Updates the status of a title in the library (e.g. watching, completed, on_hold).
    """
    item = await library_manager.update_status(item_id, req.status)
    if not item:
        raise HTTPException(status_code=404, detail="Title not found in library")
    return item


@router.patch("/{item_id}/progress", response_model=LibraryItem)
async def update_library_progress(item_id: str, req: ProgressUpdateRequest):
    """
    Updates watching progress (season, episode, completion percentage, playback timestamps).
    """
    item = await library_manager.update_progress(
        item_id=item_id,
        season=req.season,
        episode=req.episode,
        progress_percent=req.progress_percent,
        playback_seconds=req.playback_seconds,
        duration_seconds=req.duration_seconds,
        status=req.status,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Title not found in library")
    return item


@router.delete("/{item_id}")
async def remove_library_item(item_id: str):
    """
    Removes a title from the library.
    """
    removed = await library_manager.remove_item(item_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Title not found in library")
    return {"status": "success", "message": f"Removed '{item_id}' from library"}
