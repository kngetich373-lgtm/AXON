"""Authentication contracts for AXON V15 integrations.

This layer intentionally does not store provider secrets. Concrete OAuth/API
implementations can be plugged in later without changing Agent or Tool code.
"""
from .base import AuthProvider, AuthState

__all__ = ["AuthProvider", "AuthState"]
