__all__ = ["Trail", "Peak"]


def __getattr__(name: str):
    if name == "Trail":
        from .trail import Trail

        return Trail
    if name == "Peak":
        from .peak import Peak

        return Peak
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
