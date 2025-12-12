"""GWSA MCP - Model Context Protocol server for Google Workspace Access.

This module provides an MCP server that exposes GWSA functionality
to LLM clients like Claude Code.
"""

from .server import mcp, run_server

__all__ = ["mcp", "run_server"]
