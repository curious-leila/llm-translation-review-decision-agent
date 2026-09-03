"""Standalone product-demo HTTP boundary.

This package is intentionally separate from the Day 1 engineering inspector.
"""

from review_triage.demo.app import create_app

__all__ = ["create_app"]
