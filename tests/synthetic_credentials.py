"""Ephemeral test-only authentication; never a deployable default credential."""
import secrets

TEST_PASSWORD = secrets.token_urlsafe(24)
TEST_TOKEN = secrets.token_urlsafe(32)
