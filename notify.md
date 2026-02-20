Toggle Telegram notifications for long-running sessions.

Run this bash command immediately with no additional commentary:

```bash
bash ~/.claude/hooks/toggle.sh $ARGUMENTS
```

If no argument is provided, it toggles notifications for the current project (inferred from working directory).

Examples:
- `/notify on` → enable for current project
- `/notify on all` → enable for all projects
- `/notify on attest` → enable for attest specifically
- `/notify off` → disable for current project
- `/notify off all` → disable all notifications
- `/notify reset` → start a new Telegram thread (use between task runs)
- `/notify reset all` → reset threads for all projects
- `/notify status` → show what's enabled

After running, report the single line of output and nothing else.
