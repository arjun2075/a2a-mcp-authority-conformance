# Coding Agent Handoff: Push A2A-MCP Authority Conformance Fixture to GitHub

## Objective
Push this repository, unchanged except for any strictly necessary repository metadata, to GitHub as a clean, reproducible engineering artifact.

## Important publication constraint
This work is under the OSS-004 publication gate. Do **not** turn the findings into standards claims, upstream proposals, issues, PRs, public announcements, or protocol recommendations until HO-005 / overlap review is complete.

Unless the human explicitly instructs otherwise, create the GitHub repository as **PRIVATE**.

## Repository name
`a2a-mcp-authority-conformance`

Suggested description:
`Minimal runnable conformance fixture for delegated-authority preservation and escalation detection across an A2A-to-MCP composition.`

## Required procedure

1. Open the extracted repository root.
2. Inspect `README.md`, `SPEC_NOTES.md`, and `TEST_RESULTS.txt` before making changes.
3. Do not alter the authority semantics, test cases, generated traces, or protocol-version assumptions just to make the repository look cleaner.
4. Run the fixture:

   ```bash
   python run_conformance.py
   ```

5. Run the complete test suite:

   ```bash
   python -m unittest discover -s tests -v
   ```

6. Confirm that the valid trace is allowed and executes the tool, while the invalid amount-escalation trace is denied before tool execution.
7. Confirm all tests pass. If they do not, diagnose the failure and make only the minimum correction necessary. Report any behavioral change to the human before pushing.
8. Check for secrets or machine-local artifacts. Do not commit credentials, tokens, caches, virtual environments, editor state, or generated junk.
9. Initialize Git only if this directory is not already a repository:

   ```bash
   git init
   git branch -M main
   ```

10. Review the exact commit set:

   ```bash
   git status --short
   git diff -- .
   ```

11. Stage and commit the fixture:

   ```bash
   git add .
   git commit -m "Add A2A-MCP delegated-authority conformance fixture"
   ```

12. If GitHub CLI is authenticated, create a PRIVATE repository and push:

   ```bash
   gh repo create a2a-mcp-authority-conformance \
     --private \
     --description "Minimal runnable conformance fixture for delegated-authority preservation and escalation detection across an A2A-to-MCP composition." \
     --source . \
     --remote origin \
     --push
   ```

   If the remote repository already exists, add it instead and push `main`:

   ```bash
   git remote add origin <REPO_URL>
   git push -u origin main
   ```

13. After pushing, verify:

   ```bash
   git status
   git log -1 --oneline
   git remote -v
   ```

14. Return to the human with:
   - repository URL;
   - visibility (`private` or `public`);
   - pushed branch and commit SHA;
   - exact test command and result;
   - whether the working tree is clean;
   - any files changed from the supplied artifact and why.

## Files expected in the repository

- `.gitignore`
- `README.md`
- `SPEC_NOTES.md`
- `TEST_RESULTS.txt`
- `GITHUB_PUSH_AGENT_INSTRUCTIONS.md`
- `pyproject.toml`
- `run_conformance.py`
- `conformance/__init__.py`
- `conformance/authority.py`
- `conformance/constants.py`
- `conformance/fixture.py`
- `conformance/protocols.py`
- `tests/test_conformance.py`
- `examples/agent_b_card.json`
- `examples/valid_input.json`
- `examples/invalid_input.json`
- `traces/valid_input.trace.json`
- `traces/invalid_input.trace.json`

## Acceptance criteria

The GitHub copy is acceptable only if another engineer can clone it and run:

```bash
python run_conformance.py
python -m unittest discover -s tests -v
```

and observe the valid authority-preserving execution pass and the invalid authority-escalation execution get mechanically rejected.

Do not broaden the scope beyond this fixture during the push task.
