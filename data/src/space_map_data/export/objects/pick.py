"""Shared field-picking for the object bundle's per-source blocks."""


def pick_attrs(obj: object, attrs: tuple[str, ...]) -> dict:
    """Extract non-None attributes from an object into a dict."""
    return {
        attr: value for attr in attrs if (value := getattr(obj, attr, None)) is not None
    }
