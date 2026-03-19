#!/usr/bin/env bash
# access.sh — open SSH port forwards through the bastion to cluster services.
# Run this script locally (not on the bastion).
#
# Prerequisites (AWS SSM — recommended for team use):
#   - AWS CLI v2 installed: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html
#   - Session Manager plugin installed:
#       https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html
#   - AWS credentials configured: aws configure  (or export AWS_PROFILE=<profile>)
#   - Your IAM user/role needs: ssm:StartSession on the bastion instance
#
# Prerequisites (SSH fallback — if SSM is not available):
#   - network-o11y-demo.pem in the repo root
#   - BASTION_PUBLIC_IP set, or tofu output available in terraform/
#
# Usage:
#   bash scripts/access.sh            # auto-detects SSM vs SSH
#   bash scripts/access.sh --ssh      # force SSH mode
#   bash scripts/access.sh --ssm      # force SSM mode

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
KEY_FILE="$REPO_ROOT/network-o11y-demo.pem"
CLUSTER_NAME="network-o11y-demo"
REGION="${AWS_REGION:-eu-west-1}"

# ── Parse flags ───────────────────────────────────────────────────────────────

FORCE_MODE=""
for arg in "$@"; do
  case "$arg" in
    --ssh) FORCE_MODE="ssh" ;;
    --ssm) FORCE_MODE="ssm" ;;
  esac
done

# ── Detect preferred mode ─────────────────────────────────────────────────────

detect_mode() {
  if [[ -n "$FORCE_MODE" ]]; then
    echo "$FORCE_MODE"
    return
  fi
  # Prefer SSM if the plugin and AWS CLI are available
  if command -v aws &>/dev/null && aws ssm describe-instance-information &>/dev/null 2>&1; then
    echo "ssm"
  elif [[ -f "$KEY_FILE" ]]; then
    echo "ssh"
  else
    echo "none"
  fi
}

MODE=$(detect_mode)

# ── SSM mode ──────────────────────────────────────────────────────────────────

ssm_access() {
  echo ""
  echo "Connecting via AWS SSM Session Manager (no SSH key required)."
  echo ""

  # Look up the bastion instance ID by Name tag
  INSTANCE_ID=$(aws ec2 describe-instances \
    --region "$REGION" \
    --filters \
      "Name=tag:Name,Values=${CLUSTER_NAME}-bastion" \
      "Name=instance-state-name,Values=running" \
    --query "Reservations[0].Instances[0].InstanceId" \
    --output text 2>/dev/null)

  if [[ -z "$INSTANCE_ID" || "$INSTANCE_ID" == "None" ]]; then
    echo "ERROR: Could not find a running bastion instance tagged '${CLUSTER_NAME}-bastion'." >&2
    echo "       Check that the environment is deployed: cd terraform && tofu apply" >&2
    exit 1
  fi

  echo "  Bastion instance: $INSTANCE_ID"
  echo ""
  echo "  http://localhost:8080   → NetBox UI       (network-tools/netbox:80)"
  echo "  http://localhost:12345  → Grafana Alloy UI (network-lab/alloy:12345)"
  echo "  http://localhost:9273   → gnmic metrics    (network-lab/gnmic:9273)"
  echo ""
  echo "  Press Ctrl+C to close all tunnels."
  echo ""

  # SSM port-forwarding tunnels run in the background via the SSM plugin.
  # Each tunnel opens a local port that forwards to a remote port on the bastion,
  # from which kubectl port-forward bridges into the cluster.
  #
  # First start kubectl port-forwards on the bastion itself, then open SSM tunnels.

  echo "Starting kubectl port-forwards on bastion..."
  aws ssm start-session \
    --region "$REGION" \
    --target "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters '{"commands":["kubectl port-forward -n network-tools svc/netbox 8080:80 --address=127.0.0.1 & kubectl port-forward -n network-lab svc/alloy 12345:12345 --address=127.0.0.1 & kubectl port-forward -n network-lab svc/gnmic 9273:9273 --address=127.0.0.1 & wait"]}' \
    &>/dev/null &
  KUBECTL_PID=$!
  sleep 3  # give port-forwards a moment to bind

  echo "Opening SSM port-forwarding tunnels..."
  aws ssm start-session \
    --region "$REGION" \
    --target "$INSTANCE_ID" \
    --document-name "AWS-StartPortForwardingSession" \
    --parameters '{"portNumber":["8080"],"localPortNumber":["8080"]}' &
  T1=$!

  aws ssm start-session \
    --region "$REGION" \
    --target "$INSTANCE_ID" \
    --document-name "AWS-StartPortForwardingSession" \
    --parameters '{"portNumber":["12345"],"localPortNumber":["12345"]}' &
  T2=$!

  aws ssm start-session \
    --region "$REGION" \
    --target "$INSTANCE_ID" \
    --document-name "AWS-StartPortForwardingSession" \
    --parameters '{"portNumber":["9273"],"localPortNumber":["9273"]}' &
  T3=$!

  trap "kill $KUBECTL_PID $T1 $T2 $T3 2>/dev/null; echo 'Tunnels closed.'" EXIT INT TERM
  wait $T1
}

# ── SSH mode (fallback) ───────────────────────────────────────────────────────

ssh_access() {
  if [[ ! -f "$KEY_FILE" ]]; then
    echo "ERROR: SSH key not found at $KEY_FILE" >&2
    echo "       Get it from the team vault, or use SSM: bash scripts/access.sh --ssm" >&2
    exit 1
  fi

  if [[ -z "${BASTION_PUBLIC_IP:-}" ]]; then
    echo "Fetching bastion IP from Terraform output..."
    BASTION_PUBLIC_IP=$(cd "$REPO_ROOT/terraform" && tofu output -raw bastion_public_ip 2>/dev/null) || {
      echo "ERROR: BASTION_PUBLIC_IP is not set and could not be read from Terraform output." >&2
      echo "       Run: source scripts/setup-env.sh first, or set BASTION_PUBLIC_IP manually." >&2
      exit 1
    }
  fi

  echo ""
  echo "Opening port forwards via bastion @ $BASTION_PUBLIC_IP (SSH mode)"
  echo ""
  echo "  http://localhost:8080   → NetBox UI       (network-tools/netbox:80)"
  echo "  http://localhost:12345  → Grafana Alloy UI (network-lab/alloy:12345)"
  echo "  http://localhost:9273   → gnmic metrics    (network-lab/gnmic:9273)"
  echo ""
  echo "  Press Ctrl+C to close all tunnels."
  echo ""

  ssh -N \
    -i "$KEY_FILE" \
    -o StrictHostKeyChecking=no \
    -o ServerAliveInterval=30 \
    -o ExitOnForwardFailure=yes \
    -L "8080:localhost:8080" \
    -L "12345:localhost:12345" \
    -L "9273:localhost:9273" \
    "ec2-user@$BASTION_PUBLIC_IP" \
    &
  SSH_PID=$!

  ssh -i "$KEY_FILE" \
      -o StrictHostKeyChecking=no \
      -o ServerAliveInterval=30 \
      "ec2-user@$BASTION_PUBLIC_IP" \
      "kubectl port-forward -n network-tools svc/netbox   8080:80   --address=127.0.0.1 &
       kubectl port-forward -n network-lab   svc/alloy    12345:12345 --address=127.0.0.1 &
       kubectl port-forward -n network-lab   svc/gnmic    9273:9273   --address=127.0.0.1 &
       wait" &
  KUBECTL_PID=$!

  trap "kill $SSH_PID $KUBECTL_PID 2>/dev/null; echo 'Tunnels closed.'" EXIT INT TERM
  wait $SSH_PID
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "$MODE" in
  ssm)  ssm_access ;;
  ssh)  ssh_access ;;
  none)
    echo "ERROR: Neither SSM nor SSH access is available." >&2
    echo ""
    echo "SSM (recommended — no keys needed):" >&2
    echo "  1. Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html" >&2
    echo "  2. Install the SSM plugin: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html" >&2
    echo "  3. Configure credentials: aws configure" >&2
    echo ""
    echo "SSH (fallback):" >&2
    echo "  Place network-o11y-demo.pem in the repo root (get it from the team vault)." >&2
    exit 1
    ;;
esac
