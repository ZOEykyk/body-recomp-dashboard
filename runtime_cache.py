from __future__ import annotations

from typing import Any, Callable, TypeVar


Function = TypeVar("Function", bound=Callable[..., Any])


def streamlit_cache(
    streamlit_module: Any,
    cache_name: str,
    **options: Any,
) -> Callable[[Function], Function]:
    """Use Streamlit caching while remaining importable by lightweight validators."""
    factory = getattr(streamlit_module, cache_name, None)
    if callable(factory):
        try:
            decorator = factory(**options)
            if callable(decorator):
                return decorator
        except (AttributeError, TypeError):
            pass
    return lambda function: function


def clear_cached_function(function: Callable[..., Any]) -> None:
    clear = getattr(function, "clear", None)
    if callable(clear):
        clear()


__all__ = ["clear_cached_function", "streamlit_cache"]
