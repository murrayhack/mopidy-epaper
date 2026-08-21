---
name: generating-commit-messages
description: Generates a commit message for this repo from staged git diffs (no Co-Authored-By, no Claude Code footer). Use when the user says "commit", "write a commit", "commit message", "generate a commit", "/commit", or asks to commit staged changes.
---

# Generating Commit Messages

## Instructions

1. Run `git diff --staged` to see changes
2. I'll suggest a commit message with:
   - Summary under 50 characters
   - Detailed description
   - Affected components
   - Don't include 🤖 Generated with [Claude Code](https://claude.com/claude-code) in the commit message.
   - Don't include Co-Authored-By: in the commit message.

## Best practices

- Write the commit message in English, even when the changes,
  tickets, or surrounding content are in Swedish.
- Use present tense
- Explain what and why, not how

## Repo specifics

- Never commit to `develop`, `stage` or `master` directly — those are the
  integration/staging/production branches (pushing `master` triggers the
  production deploy workflow). Branch first if the user is on one of them.
