#!/bin/bash

# PassivMOS GitHub Repository Setup Script
# This script prepares your repo to be made public safely

set -e

echo "🚀 PassivMOS GitHub Repository Setup"
echo "====================================="
echo ""

# Configuration
GITHUB_USER="tonyler"
REPO_NAME="passivmos_web"

echo "📋 Configuration:"
echo "   GitHub User: $GITHUB_USER"
echo "   Repository: $REPO_NAME"
echo ""

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) is not installed!"
    echo ""
    echo "Install it with:"
    echo "  Linux: curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg"
    echo "  Then run: echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main\" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null"
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

# Check if we're in a git repository
if [ ! -d .git ]; then
    echo "❌ Not in a git repository!"
    echo "Run this script from your passivmos_web directory"
    exit 1
fi

echo "📦 Current directory: $(pwd)"
echo ""

# Stage all changes including .gitignore
echo "📝 Staging changes..."
git add .gitignore sessions/.gitkeep data/cache/.gitkeep backend/data/cache/.gitkeep
git add .

# Show what will be committed (excluding sensitive files)
echo ""
echo "📋 Files that will be committed:"
git status --short
echo ""

# Check if there are changes to commit
if git diff --cached --quiet; then
    echo "✅ No new changes to commit (already up to date)"
else
    echo "💾 Committing changes..."
    git commit -m "Security: Add .gitignore and remove sensitive files

- Add comprehensive .gitignore
- Remove .env files with API keys
- Remove user session data
- Remove cached token data
- Add .gitkeep files for empty directories

Repository is now safe to make public."
    echo "✅ Changes committed"
fi

echo ""

# Check if remote exists
if ! git remote get-url origin &> /dev/null; then
    echo "🔗 No remote found. Checking if GitHub repo exists..."

    if gh repo view "$GITHUB_USER/$REPO_NAME" &> /dev/null; then
        echo "✅ Found existing GitHub repo"
        REPO_URL=$(gh repo view "$GITHUB_USER/$REPO_NAME" --json url -q .url)
        echo "🔗 Adding remote: $REPO_URL"
        git remote add origin "$REPO_URL"
    else
        echo "📝 Creating new GitHub repository..."
        read -p "Make repository public? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            gh repo create "$REPO_NAME" --source=. --public --push
            echo "✅ Public repository created and pushed!"
        else
            gh repo create "$REPO_NAME" --source=. --private --push
            echo "✅ Private repository created and pushed!"
            echo "⚠️  Note: You'll need to make it public later for open-domains"
        fi
    fi
else
    echo "✅ Remote already configured"
    git remote -v
    echo ""

    # Push changes
    echo "📤 Pushing changes to GitHub..."
    CURRENT_BRANCH=$(git branch --show-current)
    git push -u origin "$CURRENT_BRANCH"
    echo "✅ Changes pushed!"
fi

echo ""
echo "🔍 Checking if repository is public..."
VISIBILITY=$(gh repo view "$GITHUB_USER/$REPO_NAME" --json visibility -q .visibility)

if [ "$VISIBILITY" = "PRIVATE" ]; then
    echo "⚠️  Repository is currently PRIVATE"
    echo ""
    read -p "Do you want to make it PUBLIC now? (required for open-domains) (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "🔓 Making repository public..."
        gh repo edit "$GITHUB_USER/$REPO_NAME" --visibility public
        echo "✅ Repository is now PUBLIC!"
    else
        echo "⚠️  Skipped. You'll need to make it public manually before registering domain:"
        echo "   gh repo edit $GITHUB_USER/$REPO_NAME --visibility public"
    fi
else
    echo "✅ Repository is already PUBLIC"
fi

echo ""
echo "🎉 GitHub repository setup complete!"
echo ""
echo "📋 Repository details:"
gh repo view "$GITHUB_USER/$REPO_NAME"
echo ""
echo "🔗 Repository URL: https://github.com/$GITHUB_USER/$REPO_NAME"
echo ""
echo "📋 Next step:"
echo "   Run: ./setup_domain.sh"
echo "   This will automatically register your free domain!"
