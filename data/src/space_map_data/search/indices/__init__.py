"""Registry of search indices.

The catalog is a single index of heterogeneous documents (objects, features,
groups) discriminated by ``kind``. ``Index`` describes the uid, settings, and
how to stream documents from the export.
"""

from .base import Index
from .catalog import CATALOG_INDEX

ALL: dict[str, Index] = {CATALOG_INDEX.uid: CATALOG_INDEX}
