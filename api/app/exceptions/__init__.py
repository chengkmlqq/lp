"""Custom exceptions for the application."""

from .menu_exceptions import (
    DuplicateMenuCodeError,
    EmptyMenuCodeError,
    EmptyMenuNameError,
    MenuValidationError,
    ParentNotFoundError,
    RemovedMenuCodeError,
    SelfParentError,
)

__all__ = [
    "MenuValidationError",
    "EmptyMenuCodeError",
    "EmptyMenuNameError",
    "DuplicateMenuCodeError",
    "RemovedMenuCodeError",
    "SelfParentError",
    "ParentNotFoundError",
]
