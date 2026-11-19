#!/bin/zsh
# Manage only this user's LaunchAgent for the selected role.
set -eu
root="${0:A:h:h}"
role="$1"
action="${2:-status}"
label="local.bildirim.${role}"
domain="gui/$(id -u)"
target="$domain/$label"
plist="$HOME/Library/LaunchAgents/$label.plist"
case "$action" in
  start)
    mkdir -p "${plist:h}" "$root/data/logs"
    "$root/.venv/bin/python" - "$root" "$role" "$plist" <<'PY'
import plistlib, sys
from pathlib import Path

root, role, plist = sys.argv[1:]
args = ["mail"] if role == "mail" else ["agent", "--role", "mac-m4"]
prefix = f"{root}/data/logs/{role}-bot"
descriptor = {
    "Label": f"local.bildirim.{role}",
    "ProgramArguments": [f"{root}/.venv/bin/python", "-m", "bildirim", *args],
    "WorkingDirectory": root, "RunAtLoad": True, "KeepAlive": True,
    "ThrottleInterval": 5, "LimitLoadToSessionType": "Aqua", "ProcessType": "Background",
    "StandardOutPath": prefix + ".out.log", "StandardErrorPath": prefix + ".err.log",
    "EnvironmentVariables": {
        "PATH": f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()), "PYTHONUNBUFFERED": "1",
    },
}
Path(plist).write_bytes(plistlib.dumps(descriptor))
PY
    if launchctl print "$target" >/dev/null 2>&1; then
      launchctl bootout "$target"
    fi
    launchctl enable "$target"
    launchctl bootstrap "$domain" "$plist"
    ;;
  stop)
    if launchctl print "$target" >/dev/null 2>&1; then
      launchctl bootout "$target"
    fi
    launchctl disable "$target"
    ;;
  status)
    launchctl print "$target" 2>/dev/null | awk '/state =/{ print $0; found=1; exit } END { if (!found) print "stopped" }'
    ;;
  *) print -u2 'start | stop | status'; exit 2 ;;
esac
