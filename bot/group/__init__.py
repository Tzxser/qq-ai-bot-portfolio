"""Controlled group features for the QQ bot.

All group capabilities are fail-closed until an explicit allow-list is set.
"""

from .router import GroupRouter
from .welcome import WelcomeService
from .directory import DepartmentDirectory

__all__ = ["GroupRouter", "WelcomeService", "DepartmentDirectory"]
