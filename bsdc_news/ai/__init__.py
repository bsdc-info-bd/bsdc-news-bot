"""AI writers: several free providers behind one interface with automatic failover."""

from .base import AIProvider, ArticleDraft, GenerationRequest
from .router import AIRouter, build_router

__all__ = ["AIProvider", "ArticleDraft", "GenerationRequest", "AIRouter", "build_router"]
