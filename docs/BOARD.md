# The board

`jobveyra board render` writes a Markdown checklist of everything that needs you: portals to sign
in to, open questions, applications to look for on a portal, stuck jobs, and recent submissions to
record a reply on. Tick boxes, or answer a question with a reply such as `Q3: Yes, from January`.
`jobveyra board apply <file>` and `jobveyra board comment <file>` apply them; ticks already applied
are ignored, so running them twice is safe.

Any editor with Markdown checkboxes works. On GitHub, keep the workspace in a **private** repository
and use one issue as the board:

```yaml
# .github/workflows/board.yml in your private workspace repository
name: board
on:
  issues: {types: [edited]}
  issue_comment: {types: [created]}
  schedule: [{cron: "17 */3 * * *"}]
  workflow_dispatch:
permissions: {contents: write, issues: write}
jobs:
  sync:
    # only the board issue, and only comments from the repository owner
    if: >-
      (github.event_name != 'issues' && github.event_name != 'issue_comment') ||
      (github.event.issue.number == fromJSON(vars.BOARD_ISSUE) &&
       (github.event_name == 'issues' || github.event.comment.author_association == 'OWNER'))
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install jobveyra
      - name: Apply ticks and replies
        env:
          GH_TOKEN: ${{ github.token }}
          JOBVEYRA_HOME: ${{ github.workspace }}
          BOARD_ISSUE: ${{ vars.BOARD_ISSUE }}
          EVENT: ${{ github.event_name }}
          COMMENT_BODY: ${{ github.event.comment.body }}   # passed as data, never pasted into the script
        run: |
          gh issue view "$BOARD_ISSUE" --json body -q .body > /tmp/board.md
          jobveyra board apply /tmp/board.md
          if [ "$EVENT" = issue_comment ]; then
            printf '%s' "$COMMENT_BODY" > /tmp/comment.md
            jobveyra board comment /tmp/comment.md
          fi
          jobveyra board render --out /tmp/new.md
          gh issue edit "$BOARD_ISSUE" --body-file /tmp/new.md
      - name: Save state
        run: |
          git config user.name "board"; git config user.email "board@users.noreply.github.com"
          git add state learnings.md 2>/dev/null; git commit -qm "board sync" || true; git push
```

Set the repository variable `BOARD_ISSUE` to the issue number. Comment text reaches the script only
through an environment variable, so a comment can never run as a command.
