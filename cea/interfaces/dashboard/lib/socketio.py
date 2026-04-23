import asyncio
from typing import Any, Optional

import socketio

from socketio.exceptions import ConnectionRefusedError

from cea.interfaces.dashboard.dependencies import settings
from cea.interfaces.dashboard.lib.cache.settings import cache_settings
from cea.interfaces.dashboard.lib.database.models import LOCAL_USER_ID
from cea.interfaces.dashboard.lib.logs import getCEAServerLogger
from cea.interfaces.dashboard.settings import get_settings

logger = getCEAServerLogger("cea-server-socketio")


def _get_cors_origin():
    cors_origin = get_settings().cors_origin
    # Disable cors_origin if wildcard given
    if cors_origin == '*':
        return []

    return cors_origin


def _get_client_manager():
    if cache_settings.host and cache_settings.port:
        try:
            mgr = socketio.AsyncRedisManager(f'redis://{cache_settings.host}:{cache_settings.port}',
                                             write_only=False,  # Ensure reading is enabled
                                             channel='socketio',  # Use a consistent channel name
                                             )
            logger.info(f'Using Redis as message broker [{cache_settings.host}:{cache_settings.port}]')
            return mgr
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")

    return None


client_manager = _get_client_manager()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=_get_cors_origin(),
                           client_manager=client_manager)
socket_app = socketio.ASGIApp(sio)


async def emit_with_retry(event: str, data: Any, room: Optional[str] = None, max_retries: int = 3,
                          initial_delay: float = 0.1, backoff_factor: float = 2.0):
    """
    Emit a socketio event with retry logic and exponential backoff.

    Args:
        event: The event name to emit
        data: The data to send with the event
        room: The room to emit to (optional)
        max_retries: Maximum number of retry attempts (default: 3)
        initial_delay: Initial delay in seconds before first retry (default: 0.1)
        backoff_factor: Multiplier for delay between retries (default: 2.0)

    Returns:
        True if successful, False if all retries failed
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries + 1):  # +1 to include the initial attempt
        try:
            if room:
                await sio.emit(event, data, room=room)
            else:
                await sio.emit(event, data)

            if attempt > 0:
                logger.debug(f"Successfully emitted '{event}' after {attempt} retry attempt(s)")
            return True

        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    f"Failed to emit '{event}' (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(
                    f"Failed to emit '{event}' after {max_retries + 1} attempts. "
                    f"Last error: {last_exception}"
                )

    return False


@sio.event
async def connect(sid, environ, auth):
    if settings.local:
        await sio.enter_room(sid, f"user-{LOCAL_USER_ID}")
        return True

    # Auth is handled upstream by oauth2-proxy; the user id is forwarded
    # via the X-Auth-Request-User header by the traefik ForwardAuth middleware.
    user_id = environ.get('HTTP_X_AUTH_REQUEST_USER')
    if not user_id:
        logger.error('authentication failed: no forwarded user header')
        raise ConnectionRefusedError('authentication failed. no forwarded user header')

    await sio.enter_room(sid, f"user-{user_id}")

    return True
