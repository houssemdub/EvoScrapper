"""
routers/profiles.py — Household Multi-User Profiles & PIN Verification (T4.4)
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.profile_manager import get_profile_manager
from core.security import verify_api_key

router = APIRouter(prefix="/api/v1/profiles", tags=["Profiles"])


class ProfileCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    avatar: str = Field("avatar_1", max_length=50)
    pin: Optional[str] = Field(None, max_length=10)
    is_kids: bool = False


class PinVerifyRequest(BaseModel):
    pin: str = Field(..., max_length=10)


@router.get("", response_model=List[Dict[str, Any]])
async def list_profiles():
    """Returns list of household profiles."""
    mgr = get_profile_manager()
    return await mgr.list_profiles()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_profile(req: ProfileCreateRequest):
    """Creates a new user profile with optional PIN lock and kids mode."""
    mgr = get_profile_manager()
    return await mgr.create_profile(
        name=req.name,
        avatar=req.avatar,
        pin=req.pin,
        is_kids=req.is_kids,
    )


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    """Gets a specific profile details."""
    mgr = get_profile_manager()
    prof = await mgr.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")
    return prof


@router.post("/{profile_id}/verify-pin")
async def verify_profile_pin(profile_id: str, req: PinVerifyRequest):
    """Verifies profile PIN for access."""
    mgr = get_profile_manager()
    prof = await mgr.get_profile(profile_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Profile not found")

    valid = await mgr.verify_pin(profile_id, req.pin)
    if not valid:
        raise HTTPException(status_code=403, detail="Invalid PIN")
    return {"status": "ok", "profile_id": profile_id, "verified": True}


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    """Deletes a profile (cannot delete last remaining profile)."""
    mgr = get_profile_manager()
    success = await mgr.delete_profile(profile_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete last remaining profile or profile not found")
    return {"status": "ok", "deleted": profile_id}
