"""Imports ``smartmoneyconcepts`` with its console banner silenced.

The library prints a banner with a non-cp1252 character on import, which raises
``UnicodeEncodeError`` on a default Windows console. Redirecting stdout during the
import keeps it quiet everywhere.
"""

import contextlib
import io

with contextlib.redirect_stdout(io.StringIO()):
    from smartmoneyconcepts import smc

__all__ = ["smc"]
