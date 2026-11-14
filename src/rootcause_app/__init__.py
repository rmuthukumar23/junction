"""The Root Cause browser app and evaluation commands.

    python -m rootcause_app                 serve the dashboard on http://127.0.0.1:8765
    python -m rootcause_app.evaluate        run the comparator policies over a seed suite

Nothing here holds rules or scores of its own. The server keeps one envkit
`Episode` per run, forwards each browser request to it as a tool call, and
writes the same action trace the Harbor sidecar writes. Results are computed
by replaying that trace in a fresh engine, never read back from a file.

This package is deliberately outside `rootcause`: it is not part of the Harbor
bundle, so changing the dashboard cannot change a bundle hash or a score.
"""

DEMO_SEED = 7
DEVELOPMENT_SEEDS = (1, 2, 3, 4, 5, 6)                         # tuning suite (7-12 were also looked at)
EVALUATION_SEEDS = (101, 102, 103, 104, 105, 106, 107, 108)    # reported; never used for tuning
SCENARIO_ID = "root-cause"
