#!/bin/zsh
# Ev ağı + prizde: 09:00-18:00 sistem uyanık (ekran koruyucu serbest).
# 18:00 sonrası: aktif iş yoksa uykuya izin ver.
set -uo pipefail

ROOT="${0:A:h:h}"
STATE_DIR="$ROOT/data/awake"
LOGFILE="$STATE_DIR/awake-policy.log"
CONF="$ROOT/config/awake-policy.env"
UID_NUM="$(id -u)"
HOLD_LABEL="local.bildirim.awake.hold"
HOLD_PLIST="$HOME/Library/LaunchAgents/${HOLD_LABEL}.plist"

mkdir -p "$STATE_DIR" "$ROOT/config"

HOME_SSID=""
HOME_GATEWAY=""
DAY_START=9
DAY_END=18
BUSY_CPU=5.0

if [[ -f "$CONF" ]]; then
  # shellcheck disable=SC1090
  source "$CONF"
fi

log() {
  print -r -- "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOGFILE"
}

on_ac_power() {
  pmset -g ps 2>/dev/null | head -1 | grep -qi "AC Power"
}

wifi_ssid() {
  local ssid=""
  ssid="$(networksetup -getairportnetwork en0 2>/dev/null | sed -n 's/^Current Wi-Fi Network: //p')"
  if [[ -n "$ssid" && "$ssid" != *"not associated"* ]]; then
    print -r -- "$ssid"
    return
  fi
  print -r -- ""
}

default_gateway() {
  route -n get default 2>/dev/null | awk '/gateway:/{print $2; exit}'
}

on_home_network() {
  local ssid gateway ssid_l home_l
  ssid="$(wifi_ssid)"
  gateway="$(default_gateway)"
  ssid_l="$(print -r -- "$ssid" | tr '[:upper:]' '[:lower:]')"
  home_l="$(print -r -- "$HOME_SSID" | tr '[:upper:]' '[:lower:]')"
  if [[ -n "$ssid" && "$ssid_l" == "$home_l" ]]; then
    return 0
  fi
  # SSID okunamazsa ev ağını gateway ile tanı
  [[ -n "$HOME_GATEWAY" && "$gateway" == "$HOME_GATEWAY" ]] && return 0
  return 1
}

in_work_hours() {
  local hour
  hour="$(date '+%-H')"
  (( hour >= DAY_START && hour < DAY_END ))
}

busy_work() {
  local line cpu
  while IFS= read -r line; do
    cpu="${line%% *}"
    cpu="${cpu//,/}"
    if awk -v c="$cpu" -v t="$BUSY_CPU" 'BEGIN{exit !(c+0 >= t)}'; then
      return 0
    fi
  done < <(ps -axo %cpu=,comm= 2>/dev/null | grep -Ei "Cursor|Code Helper|omlx-server|docker|VirtualBox|Parallels" | grep -v grep || true)
  return 1
}

write_hold_plist() {
  cat > "$HOLD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${HOLD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-i</string>
    <string>-s</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF
}

hold_loaded() {
  launchctl print "gui/${UID_NUM}/${HOLD_LABEL}" >/dev/null 2>&1
}

caffeinate_running() {
  pgrep -x caffeinate >/dev/null 2>&1
}

start_caffeinate() {
  mkdir -p "${HOLD_PLIST:h}"
  write_hold_plist
  if ! hold_loaded; then
    launchctl bootstrap "gui/${UID_NUM}" "$HOLD_PLIST" 2>/dev/null || \
      launchctl load -w "$HOLD_PLIST" 2>/dev/null || true
  fi
  launchctl kickstart -k "gui/${UID_NUM}/${HOLD_LABEL}" >/dev/null 2>&1 || true
  log "hold start"
}

stop_caffeinate() {
  launchctl bootout "gui/${UID_NUM}/${HOLD_LABEL}" >/dev/null 2>&1 || true
  launchctl unload "$HOLD_PLIST" >/dev/null 2>&1 || true
  # Sadece bizim hold etiketimiz kapandı; başka caffeinate'e dokunma.
  log "hold stop"
}

status() {
  if on_ac_power; then print "power=AC"; else print "power=Battery"; fi
  print "ssid=$(wifi_ssid || true)"
  print "gateway=$(default_gateway || true)"
  if on_home_network; then print "home=yes"; else print "home=no"; fi
  if in_work_hours; then print "hours=work"; else print "hours=evening"; fi
  if hold_loaded || caffeinate_running; then print "keep_awake=yes"; else print "keep_awake=no"; fi
  if busy_work; then print "busy=yes"; else print "busy=no"; fi
}

apply() {
  if ! on_ac_power; then
    stop_caffeinate
    log "release: not on AC"
    print "released (battery)"
    return 0
  fi
  if ! on_home_network; then
    stop_caffeinate
    log "release: not home network"
    print "released (away from home network)"
    return 0
  fi
  if in_work_hours; then
    start_caffeinate
    print "holding (work hours at home on AC)"
    return 0
  fi
  if busy_work; then
    start_caffeinate
    print "holding (evening busy work)"
    return 0
  fi
  stop_caffeinate
  log "release: evening idle"
  print "released (evening idle → sleep allowed)"
}

cmd="${1:-apply}"
case "$cmd" in
  apply) apply ;;
  status) status ;;
  start) start_caffeinate; print "started" ;;
  stop) stop_caffeinate; print "stopped" ;;
  *)
    print "usage: awake-policy.sh apply|status|start|stop" >&2
    exit 2
    ;;
esac
