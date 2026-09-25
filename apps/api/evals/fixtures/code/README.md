# Eval fixture, not a repo test.

`test_calc.py` FAILS against `calc.py` as committed; that is the point.
The code-agent eval copies this directory to a temp workspace, runs the agent
against the copy, and scores whether the suite passes afterwards.
These files are never collected by the repo test suite (`testpaths = ["tests"]`).
