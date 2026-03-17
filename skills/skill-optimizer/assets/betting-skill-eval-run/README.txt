This folder stores repeatable eval artifacts for betting-skill optimization runs.

Layout:
- `<source-skill>/test-prompts.json` -> fixed prompt pack for that skill
- `<source-skill>/eval-criteria.md` -> fixed binary scoring rubric for that skill
- `<source-skill>/results.tsv` -> run history
- `<source-skill>/runs/<run-tag>/` -> per-run artifacts, logs, scores, diffs

For betting skills:
- every logged bet provides structured context
- every completed review can trigger an optimization run
- a revision is auto-applied only if the revised skill beats the baseline score

Keep each prompt pack and eval rubric stable during a single optimization pass.
