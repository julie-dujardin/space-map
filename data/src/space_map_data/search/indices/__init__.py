"""Registry of search indices.

Each module exposes an ``Index`` instance describing the index uid,
settings, and how to stream documents from the export.
"""

from .features import FEATURES_INDEX, Index
from .objects import OBJECTS_INDEX

ALL: dict[str, Index] = {idx.uid: idx for idx in [FEATURES_INDEX, OBJECTS_INDEX]}
