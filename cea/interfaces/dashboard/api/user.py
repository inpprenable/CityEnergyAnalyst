from typing import Optional

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from cea.interfaces.dashboard.dependencies import CEAUser
from cea.interfaces.dashboard.lib.database.models import LOCAL_USER_ID
from cea.interfaces.dashboard.lib.logs import getCEAServerLogger

logger = getCEAServerLogger("cea-server-user")

router = APIRouter()


class UserInfo(BaseModel):
    id: str
    primary_email: Optional[str] = None
    display_name: Optional[str] = None
    profile_image_url: Optional[str] = None


@router.get("")
async def get_user_info(user: CEAUser):
    if user.get("id") == LOCAL_USER_ID:
        return user

    return UserInfo(
        id=user.get("id"),
        display_name=user.get("display_name"),
        primary_email=user.get("primary_email"),
        profile_image_url=user.get("profile_image_url"),
    )


@router.post("/logout")
async def logout():
    # Session termination is handled by oauth2-proxy's built-in endpoint.
    return RedirectResponse(url="/oauth2/sign_out", status_code=302)
