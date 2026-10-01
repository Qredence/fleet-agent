"""The shared kernel: logic every app layer may depend on.

The kernel holds the domain rules that more than one layer needs — emission
scrubbing, write-path validation, source identity, run-input extraction, and
the storage contract. Third-party libraries (``dspy``, ``ag_ui``, ``pydantic``)
are fine here. What must never appear is an import of the app layers that
build on the kernel: ``app.agent``, ``app.agui``, ``app.api``,
``app.persistence``, ``app.services``, ``app.main``, ``app.settings``. The
rule is enforced by ``tests/test_architecture.py``.
"""
