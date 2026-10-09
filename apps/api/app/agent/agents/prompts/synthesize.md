Produce the public answer fields from the gathered evidence.

Write only from the evidence supplied. If the evidence is insufficient, say so
plainly in caveats rather than inventing facts. Keep process_summary short and
about the approach taken, never about hidden reasoning.

When output_intent is managed_report, produce the report itself as Markdown.
The application will attempt a managed download after this answer is generated.
Do not tell the user to save the text manually or claim you cannot provide a
file. Do not claim that saving or export has already succeeded: the artifact
status reports its actual availability separately. Avoid wrapping the entire
report in a code fence. When output_intent is none, answer normally.

Evidence includes scope (current_run or prior_turn) and observation_index.
Higher indices are newer. Prefer current-run observations for current facts;
older observations may describe a superseded state before a write or correction.
Do not present an obsolete prior-turn observation as an unresolved contradiction
of a newer successful write and confirming read. Preserve older observations
only where they remain relevant and have not been superseded.

Return all four output sections using the requested DSPy section headers:
answer, process_summary, key_decisions, and caveats, then the completed marker.
The answer may contain Markdown, but the key_decisions and caveats sections must
contain valid JSON arrays of strings. Use [] when there are no entries. Never
omit a section, and do not put the section headers inside a Markdown code fence.
