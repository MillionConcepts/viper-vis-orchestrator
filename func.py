"""functional utilities. note: vendored from pdr."""
from inspect import signature
from typing import Callable


def get_argnames(func: Callable) -> set[str]:
    """reads the names of the arguments the function will accept"""
    return set(signature(func).parameters.keys())
