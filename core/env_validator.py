"""Environment variable validation with helpful error messages."""
from __future__ import annotations

import os
import sys
from typing import Optional


class EnvValidationError(Exception):
    """Raised when required environment variables are missing or invalid."""
    pass


def get_required_env(name: str, description: str = "") -> str:
    """Get a required environment variable or raise a helpful error.

    Args:
        name: Environment variable name
        description: Human-readable description of what this variable is for

    Returns:
        The environment variable value (stripped of whitespace)

    Raises:
        EnvValidationError: If the variable is missing or empty
    """
    value = os.environ.get(name, "").strip()
    if not value:
        error_msg = f"Missing required environment variable: {name}"
        if description:
            error_msg += f"\n  Purpose: {description}"
        error_msg += f"\n  Please set this variable in your .env file or environment."
        raise EnvValidationError(error_msg)
    return value


def get_optional_env(name: str, default: str = "", description: str = "") -> str:
    """Get an optional environment variable with a default value.

    Args:
        name: Environment variable name
        default: Default value if not set
        description: Human-readable description

    Returns:
        The environment variable value or default
    """
    value = os.environ.get(name, "").strip()
    return value if value else default


def validate_all_required_env() -> dict[str, str]:
    """Validate all required environment variables for the application.

    Returns:
        Dictionary of validated environment variables

    Raises:
        EnvValidationError: If any required variable is missing
    """
    try:
        env_vars = {
            "SUPABASE_URL": get_required_env(
                "SUPABASE_URL",
                "Your Supabase project URL (e.g., https://xxx.supabase.co)"
            ),
            "SUPABASE_ANON_KEY": get_required_env(
                "SUPABASE_ANON_KEY",
                "Your Supabase anonymous/public API key"
            ),
            "SUPABASE_SERVICE_ROLE_KEY": get_required_env(
                "SUPABASE_SERVICE_ROLE_KEY",
                "Your Supabase service role key (keep secret!)"
            ),
            "OPENAI_API_KEY": get_required_env(
                "OPENAI_API_KEY",
                "Your OpenAI API key for embeddings"
            ),
            "ANTHROPIC_API_KEY": get_required_env(
                "ANTHROPIC_API_KEY",
                "Your Anthropic API key for Claude"
            ),
        }

        # Optional variables with defaults
        env_vars["SITE_URL"] = get_optional_env(
            "SITE_URL",
            default="https://chat.democraciamas.com",
            description="Public URL for OAuth redirects"
        )
        env_vars["EMBEDDING_MODEL"] = get_optional_env(
            "EMBEDDING_MODEL",
            default="text-embedding-3-small",
            description="OpenAI embedding model to use"
        )
        env_vars["CLAUDE_MODEL"] = get_optional_env(
            "CLAUDE_MODEL",
            default="claude-3-5-sonnet-latest",
            description="Primary Claude model to use"
        )

        return env_vars

    except EnvValidationError as e:
        print("\n" + "="*70, file=sys.stderr)
        print("CONFIGURATION ERROR", file=sys.stderr)
        print("="*70, file=sys.stderr)
        print(str(e), file=sys.stderr)
        print("\nExample .env file:", file=sys.stderr)
        print("-" * 70, file=sys.stderr)
        print("""SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=your-anon-key-here
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key-here
OPENAI_API_KEY=sk-xxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxx
SITE_URL=https://your-domain.com
EMBEDDING_MODEL=text-embedding-3-small
CLAUDE_MODEL=claude-3-5-sonnet-latest""", file=sys.stderr)
        print("="*70, file=sys.stderr)
        sys.exit(1)


def validate_supabase_url(url: str) -> str:
    """Validate and normalize Supabase URL.

    Args:
        url: The Supabase URL to validate

    Returns:
        Normalized URL with trailing slash

    Raises:
        EnvValidationError: If URL is invalid
    """
    url = url.strip()
    if not url.startswith("http"):
        raise EnvValidationError(
            f"Invalid SUPABASE_URL: {url}\n"
            "  URL must start with http:// or https://"
        )
    return url.rstrip("/") + "/"
