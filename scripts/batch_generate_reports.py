"""Batch-generate reports from rawdata using --from-cache.

STATUS: DISABLED.

This CLI drove the standalone report-generation engine that lived in
``fresh_slotlab/player_impact_analyzer.py`` (it called ``analyzer.main()``
in-process for each cached (machine, mode)). That monolith was removed in
the analyzer re-architecture (commit c72b05a); the report-production
orchestrator is being rebuilt on the SpinType-native core
(``fresh_slotlab/analyzer/core/*``).

Until the new orchestrator lands, this script is a stub: it exits non-zero
with a clear message instead of importing the deleted module. The file is
kept so the invocation path and CLI contract are documented in one place
and so callers fail loudly rather than with an ImportError.
"""

from __future__ import annotations

import sys


def main() -> None:
    sys.stderr.write(
        "batch_generate_reports.py: the report generation engine "
        "(player_impact_analyzer) was removed; rebuild pending.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
