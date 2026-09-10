# Quest NPC Lab

Before planning or changing implementation, read `docs/design.md` for agreed
scope and approval gates. Research proposals do not override those decisions.

## Git workflow

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
- A PR is not required for every change. When creating one, use exactly
  `## Why`, `## What changed`, and `## Testing` as its body sections.
  Report actual checks and results, including checks not run.

## Agent skills

### Issue tracker

Track specs and tasks in GitHub Issues. Before issue operations,
read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels. Before triaging or changing labels,
read `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout. Before exploring domain concepts or decisions,
read `docs/agents/domain.md`.
