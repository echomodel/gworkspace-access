"""MCP tools package for gwsa, auto-discovered by mcp-app.

The package itself defines no tools. Each domain submodule
(``mail.py``, ``docs.py``, ``drive.py``, ``chat.py``) carries its
own tools as plain async functions, and ``gwsa/__init__.py`` passes
all the submodules to ``App(tools_modules=[...])``. mcp-app
discovers public async coroutine functions across them via
``inspect.getmembers``.

Adding a new tool:
    1. Put the ``async def`` in the appropriate domain submodule
       (or create a new submodule for a new domain).
    2. If a new submodule, add it to ``tools_modules`` in
       ``gwsa/__init__.py``.

No re-exports here. The framework reads each submodule directly.
"""
