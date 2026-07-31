"""Sphinx configuration."""

project = "edutap.data_provider"
author = "eduTAP"
release = "0.1.0"

extensions = ["myst_parser"]
myst_enable_extensions = ["colon_fence", "deflist"]
# Heading anchors so that a cross-page link may point at a section, e.g.
# `[field kinds](reference.md#field-kinds)`.
myst_heading_anchors = 3

# `superpowers` holds the design spec and the implementation plan. They are records
# of how this package came about, not part of its manual, and they are written for a
# different toolchain — including them would make a `-W` build fail on their headings
# and cross-references.
exclude_patterns = ["_build", "superpowers"]

html_theme = "alabaster"
