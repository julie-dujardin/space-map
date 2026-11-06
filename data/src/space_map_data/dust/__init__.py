"""The 3D dust nest: one rerunnable step per layer, a merge and the gates."""

# Here and not in `merge`, so a CLI can list them without importing the build.
VARIANTS = ("open", "vergely")
DEFAULT_VARIANT = "open"
