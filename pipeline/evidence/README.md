# Full-source evidence

This folder intentionally contains no 5M+ run report yet. Run the complete
pipeline on a machine with adequate storage, then use the command in
`pipeline/RUNBOOK.md` to generate `full_run.json`. Commit that report only after
it passes and the independent dbt checks pass. Do not copy counts from the
older investigation database into this pipeline's evidence.
