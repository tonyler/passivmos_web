#!/bin/bash

# PassivMOS Domain Registration Script
# This script automates the process of registering a free domain via open-domains

set -e

echo "🚀 PassivMOS Domain Registration Script"
echo "========================================"
echo ""

# Configuration
GITHUB_USER="tonyler"
EMAIL="tonyler@pm.me"
DOMAIN="tonyler.is-not-a.dev"
SERVER_IP="2a01:4f9:c012:b061::1"  # IPv6 address
REPO_URL="https://github.com/tonyler/passivmos_web"

echo "📋 Configuration:"
echo "   GitHub User: $GITHUB_USER"
echo "   Email: $EMAIL"
echo "   Domain: $DOMAIN"
echo "   Server IP: $SERVER_IP"
echo "   Repo URL: $REPO_URL"
echo ""

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) is not installed!"
    echo ""
    echo "Install it with:"
    echo "  Linux/Mac: curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg"
    echo "  Then: echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main\" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null"
    echo "  Finally: sudo apt update && sudo apt install gh"
    echo ""
    echo "Or visit: https://cli.github.com/manual/installation"
    exit 1
fi

# Check if logged in
if ! gh auth status &> /dev/null; then
    echo "🔐 You need to login to GitHub first"
    echo "Run: gh auth login"
    echo ""
    gh auth login
fi

echo "✅ GitHub CLI is installed and authenticated"
echo ""

# Fork the open-domains repository
echo "🍴 Forking open-domains/register repository..."
if gh repo view "$GITHUB_USER/register" &> /dev/null; then
    echo "✅ Fork already exists"
else
    gh repo fork open-domains/register --clone=false
    echo "✅ Forked successfully"
fi

# Clone the forked repository
TEMP_DIR=$(mktemp -d)
echo "📥 Cloning your fork to $TEMP_DIR..."
cd "$TEMP_DIR"
gh repo clone "$GITHUB_USER/register"
cd register

# Create a new branch
BRANCH_NAME="add-$DOMAIN"
echo "🌱 Creating branch: $BRANCH_NAME"
git checkout -b "$BRANCH_NAME"

# Create the domain configuration file
DOMAIN_FILE="domains/$DOMAIN.json"
echo "📝 Creating domain configuration file: $DOMAIN_FILE"

# Note: Using AAAA record for IPv6
cat > "$DOMAIN_FILE" << EOF
{
  "description": "PassivMOS Webapp - Cosmos Passive Income Calculator",
  "repo": "$REPO_URL",
  "owner": {
    "username": "$GITHUB_USER",
    "email": "$EMAIL"
  },
  "record": {
    "AAAA": ["$SERVER_IP"]
  }
}
EOF

echo "✅ Domain configuration created"
cat "$DOMAIN_FILE"
echo ""

# Add and commit the file
echo "💾 Committing changes..."
git add "$DOMAIN_FILE"
git commit -m "Add $DOMAIN

Registering domain for PassivMOS Webapp - a Cosmos ecosystem passive income calculator.

Owner: $GITHUB_USER
Repository: $REPO_URL"

# Push to your fork
echo "📤 Pushing to your fork..."
git push origin "$BRANCH_NAME"

# Create pull request
echo "🎯 Creating pull request..."
PR_URL=$(gh pr create \
    --repo open-domains/register \
    --title "Add $DOMAIN" \
    --body "## Domain Registration Request

**Domain:** \`$DOMAIN\`
**Project:** PassivMOS Webapp
**Description:** Passive income calculator for Cosmos ecosystem wallets

### Project Details
- **Repository:** $REPO_URL
- **Owner:** @$GITHUB_USER
- **Email:** $EMAIL

### Technical Details
- Server IP: \`$SERVER_IP\` (IPv6)
- Application: FastAPI web application for cryptocurrency portfolio tracking
- Port: 8000 (will configure nginx reverse proxy for port 80)

### Purpose
This domain will be used to host a web application that helps users track their passive income from staking various Cosmos ecosystem tokens (ATOM, OSMO, SAGA, etc.).

Thank you for reviewing this request! 🙏" \
    --head "$GITHUB_USER:$BRANCH_NAME")

echo ""
echo "🎉 SUCCESS! Pull request created!"
echo "📍 PR URL: $PR_URL"
echo ""
echo "📋 Next steps:"
echo "1. Wait for the open-domains team to review (usually 24-48 hours)"
echo "2. They may ask questions in the PR - check your GitHub notifications"
echo "3. Once approved and merged, your domain will be active!"
echo "4. Start your PassivMOS app: ./start.sh"
echo "5. Configure nginx to serve on port 80 (see DEPLOYMENT.md)"
echo ""
echo "🔗 Track your PR here: $PR_URL"

# Cleanup
cd /
rm -rf "$TEMP_DIR"

echo ""
echo "✨ All done! The automated request has been submitted."
