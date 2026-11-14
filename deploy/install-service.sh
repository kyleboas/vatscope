#!/usr/bin/env bash
# Install vatscope as a service, plus vatscope-update.timer, which pulls the scope and vatscope checkouts every
# minute and restarts the site when either changed, so pushing to GitHub deploys. vatscope needs no secrets.
#
#   sudo bash deploy/install-service.sh   # system service: its own throwaway user (DynamicUser), read-only checkouts
#   bash deploy/install-service.sh        # without root: systemd user units for the current user
#
# Installing the system service removes the user units.
set -euo pipefail
command -v systemctl >/dev/null || { echo "This installs the site's Linux server (systemd). Run it there (ssh coding)." >&2; exit 1; }

SITE="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8807}"
if [[ $EUID -eq 0 ]]; then
  AGENT_USER="${SUDO_USER:-kyle}"
  AGENT_HOME="$(getent passwd "$AGENT_USER" | cut -d: -f6)"
else
  AGENT_USER="$(id -un)"; AGENT_HOME="$HOME"
fi
SCOPE="${SCOPE:-$AGENT_HOME/scope}"
[[ -f "$SCOPE/server.py" ]] || { echo "no scope checkout at $SCOPE (set SCOPE=...)" >&2; exit 1; }

# The updater: fetch, then fast-forward (not "git pull": the other sites' updaters fetch the shared scope checkout
# at the same moment), under the lock they use too. as_agent runs git as the checkouts' owner.
updater() {   # $1: how to run git as the agent user, $2: how to restart, $3: state dir
  cat <<SCRIPT
#!/usr/bin/env bash
set -uo pipefail
lock=/run/lock/scope-git.lock
{ exec 9>>"\$lock" || exec 9<"\$lock"; } 2>/dev/null && flock -w 50 9 || true
for repo in $SCOPE $SITE; do
  $1 git -C "\$repo" fetch -q origin || true
  $1 git -C "\$repo" merge --ff-only -q '@{u}' || echo "update failed in \$repo" >&2
done
exec 9>&-
now="\$(git -C $SCOPE rev-parse HEAD) \$(git -C $SITE rev-parse HEAD)"
last="\$(cat $3/revs 2>/dev/null)"
if [[ "\$now" != "\$last" ]]; then
  $2 && echo "\$now" > $3/revs && echo "deployed \$now"
fi
SCRIPT
}
TIMER='[Unit]
Description=Check for vatscope updates every minute

[Timer]
OnBootSec=2min
OnUnitActiveSec=1min
'

if [[ $EUID -eq 0 ]]; then
  # retire the user units, if they were installed first
  uid="$(id -u "$AGENT_USER")"
  if [[ -f "$AGENT_HOME/.config/systemd/user/vatscope.service" ]]; then
    sudo -u "$AGENT_USER" XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user disable --now vatscope.service vatscope-update.timer || true
    rm -f "$AGENT_HOME"/.config/systemd/user/vatscope{.service,-update.service,-update.timer} "$AGENT_HOME/.local/lib/vatscope-update.sh"
    sudo -u "$AGENT_USER" XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user daemon-reload || true
  fi
  cat > /etc/systemd/system/vatscope.service <<UNIT
[Unit]
Description=vatscope (vatscope.kyleboas.com)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
DynamicUser=true
EnvironmentFile=-/etc/vatscope.env
Environment=SCOPE_GROUND_DIR=/var/lib/vatscope/ground
StateDirectory=vatscope
ProtectHome=tmpfs
BindReadOnlyPaths=$SCOPE $SITE
ExecStart=/usr/bin/python3 $SCOPE/server.py $SITE --port $PORT --host 127.0.0.1
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
InaccessiblePaths=-/etc/agent-secrets
CapabilityBoundingSet=
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=512M

[Install]
WantedBy=multi-user.target
UNIT
  UPDATER=/usr/local/lib/vatscope-update.sh
  updater "runuser -u $AGENT_USER --" "systemctl restart vatscope.service" /var/lib/vatscope-update > "$UPDATER"
  chmod 0755 "$UPDATER"
  cat > /etc/systemd/system/vatscope-update.service <<UNIT
[Unit]
Description=Pull scope and vatscope from GitHub and restart vatscope when they change
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=*
StateDirectory=vatscope-update
ExecStart=$UPDATER
UNIT
  printf '%s\n[Install]\nWantedBy=timers.target\n' "$TIMER" > /etc/systemd/system/vatscope-update.timer
  chmod 0644 /etc/systemd/system/vatscope{.service,-update.service,-update.timer}
  systemctl daemon-reload
  systemctl enable vatscope.service >/dev/null
  systemctl enable --now vatscope-update.timer >/dev/null
  systemctl restart vatscope.service
  mkdir -p /var/lib/vatscope-update
  echo "$(git -c safe.directory='*' -C "$SCOPE" rev-parse HEAD) $(git -c safe.directory='*' -C "$SITE" rev-parse HEAD)" > /var/lib/vatscope-update/revs
  logs="journalctl -u vatscope -n 50"
else
  U="$HOME/.config/systemd/user"; STATE="$HOME/.local/state/vatscope-update"; UPDATER="$HOME/.local/lib/vatscope-update.sh"
  mkdir -p "$U" "$STATE" "$(dirname "$UPDATER")" "$HOME/.local/state/vatscope"
  cat > "$U/vatscope.service" <<UNIT
[Unit]
Description=vatscope (vatscope.kyleboas.com)
After=network-online.target

[Service]
Type=simple
Environment=SCOPE_GROUND_DIR=$HOME/.local/state/vatscope/ground
ExecStart=/usr/bin/python3 $SCOPE/server.py $SITE --port $PORT --host 127.0.0.1
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
MemoryMax=512M

[Install]
WantedBy=default.target
UNIT
  updater "" "systemctl --user restart vatscope.service" "$STATE" > "$UPDATER"
  chmod 0755 "$UPDATER"
  cat > "$U/vatscope-update.service" <<UNIT
[Unit]
Description=Pull scope and vatscope from GitHub and restart vatscope when they change

[Service]
Type=oneshot
ExecStart=$UPDATER
UNIT
  printf '%s\n[Install]\nWantedBy=timers.target\n' "$TIMER" > "$U/vatscope-update.timer"
  systemctl --user daemon-reload
  systemctl --user enable vatscope.service >/dev/null
  systemctl --user enable --now vatscope-update.timer >/dev/null
  systemctl --user restart vatscope.service
  echo "$(git -C "$SCOPE" rev-parse HEAD) $(git -C "$SITE" rev-parse HEAD)" > "$STATE/revs"
  logs="journalctl --user -u vatscope -n 50"
fi

for _ in $(seq 1 30); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT/" 2>/dev/null && { echo "vatscope is up on $PORT"; exit 0; }
  sleep 1
done
echo "vatscope did not answer; see: $logs" >&2
exit 1
