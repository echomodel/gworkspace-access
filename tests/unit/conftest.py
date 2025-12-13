"""
Unit test configuration.

This conftest overrides the session-scoped fixtures from the parent conftest
to allow unit tests to run without requiring a valid gwsa profile.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def validate_test_environment():
    """
    Override parent's validate_test_environment to skip profile validation.

    Unit tests don't need a real profile - they use mocked/isolated configs.
    """
    yield
