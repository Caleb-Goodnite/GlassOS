#!/bin/bash
# One-time setup: make the key that signs GlassOS updates.
#
#   scripts/make-signing-key.sh
#
#  1. makes a new GPG signing key (ed25519, no passphrase, so GitHub can sign unattended)
#  2. stores the private half as the APT_SIGNING_KEY secret of the GitHub repository (gh CLI)
#  3. writes the public half to overlay/usr/share/keyrings/glassos-archive-keyring.gpg, which every
#     GlassOS install uses to check that an update really came from you. Commit that file.
#  4. leaves a backup of the private key in ~/glassos-signing-key-BACKUP.asc: put it in your
#     password manager and delete the file. Without it you can't sign updates if the secret is lost.
set -euo pipefail
cd "$(dirname "$0")/.."
PUB=overlay/usr/share/keyrings/glassos-archive-keyring.gpg
BACKUP="$HOME/glassos-signing-key-BACKUP.asc"
[ ! -s "$PUB" ] || { echo "$PUB already exists: a key was made before. Delete it first to replace the key" \
  "(computers with the old key would then need it by hand)."; exit 1; }
command -v gpg >/dev/null && command -v gh >/dev/null || { echo "needs gpg and gh (brew install gnupg gh)"; exit 1; }
REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

export GNUPGHOME="$(mktemp -d)"
trap 'rm -rf "$GNUPGHOME"' EXIT
gpg --batch --passphrase '' --quick-gen-key "GlassOS updates <updates@glassos.invalid>" ed25519 sign never
FPR="$(gpg --batch --list-secret-keys --with-colons | awk -F: '$1 == "fpr" { print $10; exit }')"
mkdir -p "$(dirname "$PUB")"
gpg --batch --export "$FPR" > "$PUB"
gpg --batch --armor --export-secret-keys "$FPR" > "$BACKUP"
chmod 600 "$BACKUP"
gh secret set APT_SIGNING_KEY --repo "$REPO" < "$BACKUP"
echo
echo "Signing key $FPR"
echo "  private key: GitHub secret APT_SIGNING_KEY on $REPO, and a backup in $BACKUP"
echo "  public key:  $PUB  (commit this)"
