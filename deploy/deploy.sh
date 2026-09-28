#!/usr/bin/env bash
# Push the code to the VDS and restart. Never ships .env or the database.
#   bash deploy/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
H=${DEPLOY_HOST:-contabo}  # ssh alias; the Russian VDS is out: Anthropic returns 403 there
rsync -az --delete --exclude-from=- ./ "$H:/srv/upcopilot/app/" <<'X'
.git/
.venv/
.env
db.sqlite3
staticfiles/
__pycache__/
.DS_Store
.vscode/
.claude/
X
ssh "$H" 'set -e
cd /srv/upcopilot/app
chown -R upcopilot:upcopilot /srv/upcopilot
sudo -u upcopilot /srv/upcopilot/venv/bin/pip install -q -r requirements.txt
sudo -u upcopilot /srv/upcopilot/venv/bin/python manage.py migrate --noinput
sudo -u upcopilot /srv/upcopilot/venv/bin/python manage.py collectstatic --noinput -v 0
systemctl restart upcopilot
systemctl is-active upcopilot'
