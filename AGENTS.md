# Repository instructions

## Commit conventions

Use Conventional Commit subjects in the form `type(scope): summary`.

- Use a lowercase type and a meaningful lowercase scope, such as `network`,
  `pikvm`, `hayase`, `migration`, or `repo`.
- Choose the type that describes the change: `feat`, `fix`, `docs`, `refactor`,
  `perf`, `test`, `build`, `ci`, `chore`, or `revert`.
- Start the summary with a lowercase imperative verb, omit a trailing period,
  and aim for a subject of 72 characters or fewer.
- Describe the actual change. Avoid unscoped milestone subjects such as
  "Complete restoration" or "Record completed deployment".
- Keep each commit focused on one cohesive scope. Review existing dirty work
  and commit unrelated changes separately using explicit file paths.

Examples: `fix(network): preserve fabric settings during startup`,
`chore(hayase): update to 6.5.8`, and
`docs(repo): document commit conventions`.

## History and publication

Sign every commit, including commits recreated by a rebase. Preserve linear
history by rebasing onto `main` and fast-forwarding; do not add merge commits.
When the user authorizes rewriting published history, use an explicit
`--force-with-lease` against the inspected remote head. Verify signatures and
the resulting diff before publishing. A message-only rewrite must preserve
every rewritten commit's tree.

Keep plaintext credentials and private keys out of commits. Commit encrypted
secret files and public keys only, and run the repository secret scan before
publishing scoped changes.
