# Third-party notices — benchmark/context-bench

The synthetic corpus files in `files/` and the judge rubric in
`upstream/rubric.txt` are sourced from the letta-evals repository
(https://github.com/letta-ai/letta-evals), Apache License 2.0:

- `letta-leaderboard/filesystem-agent/files/*.txt` → `files/`
- `letta-leaderboard/filesystem-agent/rubric.txt` → `upstream/rubric.txt`

Copyright notice retained from the upstream repository; the license text is
available at https://github.com/letta-ai/letta-evals/blob/main/LICENSE.

The 15 pinned samples in `pilot.json` are quoted (with attribution fields)
from `letta-leaderboard/filesystem-agent/datasets/filesystem_cloud.jsonl`
under the same license, and are used only as benchmark inputs with their
ground-truth answers for rubric judging — the same use the upstream harness
makes of them.

No dataset-specific license beyond the repository license was found upstream;
if you redistribute any of these artifacts, confirm reuse rights with Letta.
