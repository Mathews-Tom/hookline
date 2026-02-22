Toggle Telegram notifications for long-running sessions.

Run this bash command immediately with no additional commentary:

```bash
python3 -m hookline $ARGUMENTS
```

If no argument is provided, it toggles notifications for the current project (inferred from working directory).

Examples:
- `/hookline on` → enable for current project
- `/hookline on all` → enable for all projects
- `/hookline on attest` → enable for attest specifically
- `/hookline off` → disable for current project
- `/hookline off all` → disable all notifications
- `/hookline reset` → start a new Telegram thread (use between task runs)
- `/hookline reset all` → reset threads for all projects
- `/hookline status` → show what's enabled

After running, report the single line of output and nothing else.
