"""Database-backed rate limiting system.

This module provides rate limiting functionality that persists across sessions
and works correctly with Streamlit's multi-tab/multi-user environment.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from .supabase_client import svc


def check_rate_limit(
    user_id: str,
    action: str = "chat_message",
    max_requests: int = 10,
    window_seconds: int = 60
) -> tuple[bool, Optional[int]]:
    """Check if a user has exceeded their rate limit.

    This function stores rate limit data in Supabase, making it persistent
    across sessions and preventing bypass through page refresh.

    Args:
        user_id: The user's ID
        action: The action being rate limited (e.g., "chat_message")
        max_requests: Maximum number of requests allowed in the window
        window_seconds: Time window in seconds

    Returns:
        Tuple of (is_allowed, seconds_until_reset)
        - is_allowed: True if the request is allowed, False if rate limited
        - seconds_until_reset: Seconds until rate limit resets (None if allowed)

    Example:
        allowed, wait_time = check_rate_limit(user_id, "chat_message", 10, 60)
        if not allowed:
            st.error(f"Rate limited. Try again in {wait_time} seconds.")
            st.stop()
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=window_seconds)

    # Get recent requests from the database
    try:
        result = (
            svc.table("rate_limits")
            .select("created_at")
            .eq("user_id", user_id)
            .eq("action", action)
            .gte("created_at", window_start.isoformat())
            .order("created_at", desc=False)
            .execute()
        )
        recent_requests = result.data or []
    except Exception:
        # If rate_limits table doesn't exist or query fails, allow the request
        # This ensures the app doesn't break if the table hasn't been created yet
        recent_requests = []

    # Check if limit exceeded
    if len(recent_requests) >= max_requests:
        # Calculate when the oldest request will expire
        oldest_request_time = datetime.fromisoformat(
            recent_requests[0]["created_at"].replace("Z", "+00:00")
        )
        reset_time = oldest_request_time + timedelta(seconds=window_seconds)
        seconds_until_reset = int((reset_time - now).total_seconds()) + 1
        return False, max(1, seconds_until_reset)

    # Record this request
    try:
        svc.table("rate_limits").insert({
            "user_id": user_id,
            "action": action,
            "created_at": now.isoformat(),
        }).execute()
    except Exception:
        # If insert fails (e.g., table doesn't exist), allow the request anyway
        # This prevents the app from breaking during migration
        pass

    return True, None


def cleanup_old_rate_limits(days_to_keep: int = 7) -> int:
    """Clean up old rate limit records to prevent table bloat.

    This should be called periodically (e.g., daily cron job).

    Args:
        days_to_keep: Number of days of rate limit data to keep

    Returns:
        Number of records deleted
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

    try:
        result = (
            svc.table("rate_limits")
            .delete()
            .lt("created_at", cutoff.isoformat())
            .execute()
        )
        # PostgREST doesn't return count directly, but we can infer success
        return len(result.data) if result.data else 0
    except Exception:
        return 0


def get_user_request_count(
    user_id: str,
    action: str = "chat_message",
    window_seconds: int = 60
) -> int:
    """Get the number of requests a user has made in the current window.

    Args:
        user_id: The user's ID
        action: The action being tracked
        window_seconds: Time window in seconds

    Returns:
        Number of requests in the current window
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=window_seconds)

    try:
        result = (
            svc.table("rate_limits")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("action", action)
            .gte("created_at", window_start.isoformat())
            .execute()
        )
        return result.count if hasattr(result, "count") else len(result.data or [])
    except Exception:
        return 0
