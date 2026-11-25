"""Preserve python -m app.experiments as the supported CLI."""
from app.experiments.cli import cli

raise SystemExit(cli())
