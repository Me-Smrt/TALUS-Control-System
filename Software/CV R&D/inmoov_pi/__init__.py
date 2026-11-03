"""Raspberry Pi control-plane support for the InMoov CV/IK project.

The modules in this package deliberately sit around the perception/IK code rather
than inside it.  They own state publication, camera snapshot service, health
sampling, and the read-only API used by the dashboard / future auxiliary node.
"""

__version__ = "0.3.0"
