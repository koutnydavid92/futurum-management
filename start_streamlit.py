#!/usr/bin/env python3
"""Wrapper to launch Streamlit with correct working directory."""
import os
import sys

# Set working directory before streamlit tries os.getcwd()
_project = os.path.dirname(os.path.abspath(__file__))
os.chdir(_project)

# Get port from env or default
port = os.environ.get("PORT", "8501")

sys.argv = [
    "streamlit", "run",
    os.path.join(_project, "app.py"),
    "--server.headless", "true",
    "--server.port", port,
]

from streamlit.web.cli import main
main()
