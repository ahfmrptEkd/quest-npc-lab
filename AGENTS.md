# Quest NPC Lab

Before planning or changing implementation, read `docs/design.md` for agreed
scope and approval gates. Research proposals do not override those decisions.

## Git workflow

- Never push implementation commits directly to `main`. All implementation
  changes landing in `main` must arrive via pull requests.
- When delegating implementation tickets or parallel tasks to subagents or
  workflows, each worker must operate in a dedicated `git worktree` on a
  short-lived branch (e.g. `.worktrees/<branch>`) rather than mutating the root
  workspace.
- PR merges between worktrees or intermediate feature branches are permitted.
- Clean up temporary worktrees (`git worktree remove`) after the branch is pushed
  or merged.
- After each coherent, approved task, verify the change and review the staged
  diff for unintended files, personal information, and secrets. Then commit
  and push without requesting separate permission for those Git operations.
- If required checks fail, fix the failure or report the blocker before
  committing. Report push failures; never force-push to resolve them.
- Commit messages contain one line and no body:
  `<type>(<category>): <head message>`.
  Example: `doc(agents): configure repository skill conventions`.
  Use types such as `feat`, `fix`, `doc`, `refactor`, `test`, and `chore`;
  category names the affected area.
- Implementation tickets use short-lived branches and PRs. PR bodies use
  exactly `## Why`, `## What changed`, and `## Testing` as their sections.
  Report actual checks and results, including checks not run.

## Agent skills

### Engineering flow

Use `/ask-matt` to select the applicable skill flow. The project's main route
is `/grill-with-docs` → `/to-spec` → `/to-tickets` → `/implement`, with `/tdd`
and `/code-review`, followed by PR checks and review feedback. Keep detailed
procedures in the selected skills.

If `docs/agents/workflow.md` exists, read it for local delegation preferences;
otherwise continue with the public rules above.

### Issue tracker

Track specs and tasks in GitHub Issues. Before issue operations,
read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels. Before triaging or changing labels,
read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout. Before exploring domain concepts or decisions,
read `docs/agents/domain.md`.
