"""The scheduler's job table must account for every download provider."""

from collections import Counter

from space_map_data.download.common import ALL_SOURCES
from space_map_data.scheduler.__main__ import JOBS


class TestJobCoverage:
    """Guards against a provider being added and never scheduled."""

    def test_every_source_is_scheduled(self):
        scheduled = {source for job in JOBS for source in job.sources}
        assert scheduled == set(ALL_SOURCES)

    def test_no_source_is_scheduled_twice(self):
        counts = Counter(source for job in JOBS for source in job.sources)
        assert [name for name, n in counts.items() if n > 1] == []

    def test_job_names_are_unique(self):
        names = [job.name for job in JOBS]
        assert len(set(names)) == len(names)
