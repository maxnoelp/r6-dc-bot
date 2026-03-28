"""
Shared pytest fixtures and environment setup.

Sets dummy environment variables before any module that reads config is imported.
This prevents pydantic-settings from raising a ValidationError in CI.
"""

import os

os.environ.setdefault("DISCORD_TOKEN", "fake-token")
os.environ.setdefault("R6DATA_API_KEY", "fake-key")
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
os.environ.setdefault("ANTHROPIC_API_KEY", "fake-key")
