---
name: creating-pull-requests
description: Creates a GitHub pull request for the current branch following this repo's template and conventions. Use when the user says "create a PR", "open a PR", "make a pull request", or similar.
---

# Creating Pull Requests

This repo's PR conventions:

- **Base branch:** the repo's default branch (usually `main`). If the current branch was cut from something else, say so and ask which base is intended.
- **Template:** use `.github/pull_request_template.md` if the repo has one, matching its sections verbatim. Otherwise use a simple `## Summary` + `## Changes` structure.
- **Title:** a concise, human summary. Under ~70 chars. Never leave the auto-generated branch-name title.

## Instructions

1. Gather state in parallel:
   - `git status` (no `-uall`)
   - `git log --oneline origin/<base>..HEAD` to see commits on this branch
   - `git diff origin/<base>...HEAD` to understand the full change set (NOT just the latest commit)
   - `git rev-parse --abbrev-ref --symbolic-full-name @{u}` to confirm upstream is set
   (`<base>` is the branch's actual base, usually `main`)
2. If the branch has no upstream, push with `git push -u origin <branch>`. If commits are ahead of upstream, push them.
3. Draft the PR body in English, following the template/structure from the bullet above:
   - Summary/Changes section — bullets summarizing the changes across ALL commits on the branch (not just HEAD). Lead with what changed; add a nested sub-bullet for the *why* when the reason isn't obvious from the change itself.
   - Add a screenshots/verification section only when there's something concrete to show. Never invent screenshots.
4. Create the PR with `gh pr create --base <base> --title "<title>" --body "$(cat <<'EOF' ... EOF)"`. Always pass the body via heredoc to preserve formatting.
5. Return the PR URL printed by `gh`.

## Rules

- **Never** target a production/deploy branch unless the user explicitly says so.
- Do NOT include `🤖 Generated with [Claude Code]` or `Co-Authored-By:` lines in the PR body.
- Do NOT push directly to the base branch. Only push the feature branch.
- If the working tree is dirty, ask the user whether to commit, stash, or abort before creating the PR.
