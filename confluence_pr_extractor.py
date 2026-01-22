#!/usr/bin/env python3
"""
Confluence PR Extractor

Extracts GitHub PR links from a Confluence page and reports their status:
- Merge status (merged, open, closed)
- Approval status (approved, changes requested, pending review)
- CI check status (pass/fail for each check)

Supports both Confluence Cloud and Confluence Server/Data Center.
"""

import os
import sys
import re
import json
import argparse
import subprocess
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import base64

# Try to import requests, fall back to urllib if not available
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request
    import urllib.error
    import ssl


class PRState(Enum):
    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class ReviewState(Enum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    PENDING = "pending"
    REVIEW_REQUIRED = "review_required"
    UNKNOWN = "unknown"


class CheckStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    ERROR = "error"
    NEUTRAL = "neutral"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    conclusion: Optional[str] = None


@dataclass
class ReviewInfo:
    reviewer: str
    state: ReviewState


@dataclass
class PRStatus:
    url: str
    repo: str
    number: int
    title: str = "Unknown"
    state: PRState = PRState.UNKNOWN
    author: str = ""
    review_state: ReviewState = ReviewState.UNKNOWN
    reviews: list[ReviewInfo] = field(default_factory=list)
    approvals_count: int = 0
    required_approvals: int = 0
    checks: list[CheckResult] = field(default_factory=list)
    checks_passed: bool = False
    checks_total: int = 0
    checks_success: int = 0
    checks_failed: int = 0
    checks_pending: int = 0
    mergeable: Optional[bool] = None
    draft: bool = False
    error: Optional[str] = None


class ConfluencePRExtractor:
    """Extract PRs from Confluence and check their GitHub status."""
    
    # Patterns to match GitHub PR URLs
    PR_PATTERNS = [
        # Standard GitHub PR URL
        r'https?://github\.com/([^/]+/[^/]+)/pull/(\d+)',
        # GitHub Enterprise
        r'https?://[^/]+/([^/]+/[^/]+)/pull/(\d+)',
    ]
    
    def __init__(
        self,
        confluence_url: str,
        confluence_user: Optional[str] = None,
        confluence_token: Optional[str] = None,
        github_token: Optional[str] = None
    ):
        self.confluence_url = confluence_url
        self.confluence_user = confluence_user or os.environ.get("CONFLUENCE_USER")
        self.confluence_token = confluence_token or os.environ.get("CONFLUENCE_TOKEN")
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        
        self.pr_statuses: list[PRStatus] = []
    
    def _make_request(self, url: str, headers: dict = None) -> tuple[bool, str]:
        """Make an HTTP request and return the response."""
        headers = headers or {}
        
        if HAS_REQUESTS:
            try:
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                return True, response.text
            except requests.RequestException as e:
                return False, str(e)
        else:
            # Fallback to urllib
            try:
                req = urllib.request.Request(url, headers=headers)
                # Create SSL context that doesn't verify (for self-signed certs)
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                
                with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
                    return True, response.read().decode('utf-8')
            except urllib.error.URLError as e:
                return False, str(e)
    
    def _get_confluence_auth_header(self) -> dict:
        """Get authentication header for Confluence."""
        if self.confluence_user and self.confluence_token:
            # Basic auth for Confluence Cloud (email:api_token)
            # or Confluence Server (username:password)
            credentials = f"{self.confluence_user}:{self.confluence_token}"
            encoded = base64.b64encode(credentials.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {}
    
    def fetch_confluence_page(self) -> tuple[bool, str]:
        """Fetch content from Confluence page."""
        parsed = urlparse(self.confluence_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Try to determine page ID from URL
        page_id = None
        
        # Pattern 1: /wiki/spaces/SPACE/pages/PAGE_ID/title
        match = re.search(r'/pages/(\d+)', self.confluence_url)
        if match:
            page_id = match.group(1)
        
        # Pattern 2: ?pageId=PAGE_ID
        if not page_id:
            params = parse_qs(parsed.query)
            if 'pageId' in params:
                page_id = params['pageId'][0]
        
        # Pattern 3: /display/SPACE/Page+Title (need to search)
        
        headers = self._get_confluence_auth_header()
        headers["Accept"] = "application/json"
        
        if page_id:
            # Confluence Cloud API
            api_url = f"{base_url}/wiki/rest/api/content/{page_id}?expand=body.storage"
            success, response = self._make_request(api_url, headers)
            
            if success:
                try:
                    data = json.loads(response)
                    return True, data.get("body", {}).get("storage", {}).get("value", "")
                except json.JSONDecodeError:
                    pass
            
            # Try Confluence Server/Data Center API
            api_url = f"{base_url}/rest/api/content/{page_id}?expand=body.storage"
            success, response = self._make_request(api_url, headers)
            
            if success:
                try:
                    data = json.loads(response)
                    return True, data.get("body", {}).get("storage", {}).get("value", "")
                except json.JSONDecodeError:
                    pass
        
        # Fallback: fetch the page directly and parse HTML
        success, response = self._make_request(self.confluence_url, headers)
        if success:
            return True, response
        
        return False, f"Failed to fetch Confluence page: {response}"
    
    def extract_pr_links(self, content: str) -> list[tuple[str, str, int]]:
        """Extract GitHub PR links from page content.
        
        Returns list of (full_url, repo, pr_number) tuples.
        """
        pr_links = []
        seen = set()
        
        for pattern in self.PR_PATTERNS:
            matches = re.finditer(pattern, content)
            for match in matches:
                full_url = match.group(0)
                repo = match.group(1)
                pr_number = int(match.group(2))
                
                key = (repo, pr_number)
                if key not in seen:
                    seen.add(key)
                    pr_links.append((full_url, repo, pr_number))
        
        return pr_links
    
    def get_pr_status_gh_cli(self, repo: str, pr_number: int) -> PRStatus:
        """Get PR status using GitHub CLI."""
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        status = PRStatus(url=pr_url, repo=repo, number=pr_number)
        
        try:
            # Get PR details
            result = subprocess.run(
                [
                    "gh", "pr", "view", str(pr_number),
                    "-R", repo,
                    "--json", "title,state,author,isDraft,mergeable,reviewDecision,reviews,number,url"
                ],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                status.error = f"Failed to fetch PR: {result.stderr.strip()}"
                return status
            
            data = json.loads(result.stdout)
            
            status.title = data.get("title", "Unknown")
            status.author = data.get("author", {}).get("login", "")
            status.draft = data.get("isDraft", False)
            status.mergeable = data.get("mergeable")
            
            # Determine state
            state_str = data.get("state", "").upper()
            if state_str == "MERGED":
                status.state = PRState.MERGED
            elif state_str == "CLOSED":
                status.state = PRState.CLOSED
            elif state_str == "OPEN":
                status.state = PRState.OPEN
            
            # Review decision
            review_decision = data.get("reviewDecision", "")
            if review_decision == "APPROVED":
                status.review_state = ReviewState.APPROVED
            elif review_decision == "CHANGES_REQUESTED":
                status.review_state = ReviewState.CHANGES_REQUESTED
            elif review_decision == "REVIEW_REQUIRED":
                status.review_state = ReviewState.REVIEW_REQUIRED
            else:
                status.review_state = ReviewState.PENDING
            
            # Process reviews
            reviews = data.get("reviews", [])
            reviewer_states = {}
            for review in reviews:
                reviewer = review.get("author", {}).get("login", "Unknown")
                state = review.get("state", "").upper()
                
                review_state = ReviewState.PENDING
                if state == "APPROVED":
                    review_state = ReviewState.APPROVED
                elif state == "CHANGES_REQUESTED":
                    review_state = ReviewState.CHANGES_REQUESTED
                
                # Keep the latest review state for each reviewer
                reviewer_states[reviewer] = review_state
            
            for reviewer, state in reviewer_states.items():
                status.reviews.append(ReviewInfo(reviewer=reviewer, state=state))
                if state == ReviewState.APPROVED:
                    status.approvals_count += 1
            
            # Get check status
            checks_result = subprocess.run(
                [
                    "gh", "pr", "checks", str(pr_number),
                    "-R", repo,
                    "--json", "name,state,conclusion"
                ],
                capture_output=True,
                text=True,
                check=False
            )
            
            if checks_result.returncode == 0:
                checks_data = json.loads(checks_result.stdout)
                all_passed = True
                
                for check in checks_data:
                    name = check.get("name", "Unknown")
                    state = check.get("state", "").lower()
                    conclusion = check.get("conclusion", "").lower()
                    
                    check_status = CheckStatus.PENDING
                    
                    if state in ["completed", "success"]:
                        if conclusion in ["success", "neutral", "skipped"]:
                            check_status = CheckStatus.SUCCESS
                            status.checks_success += 1
                        elif conclusion == "failure":
                            check_status = CheckStatus.FAILURE
                            status.checks_failed += 1
                            all_passed = False
                        else:
                            check_status = CheckStatus.ERROR
                            status.checks_failed += 1
                            all_passed = False
                    elif state in ["pending", "in_progress", "queued", "waiting"]:
                        check_status = CheckStatus.PENDING
                        status.checks_pending += 1
                        all_passed = False
                    elif state == "failure":
                        check_status = CheckStatus.FAILURE
                        status.checks_failed += 1
                        all_passed = False
                    
                    status.checks.append(CheckResult(
                        name=name,
                        status=check_status,
                        conclusion=conclusion
                    ))
                
                status.checks_total = len(checks_data)
                status.checks_passed = all_passed and status.checks_total > 0
            
        except json.JSONDecodeError as e:
            status.error = f"Failed to parse response: {e}"
        except FileNotFoundError:
            status.error = "GitHub CLI (gh) not found. Please install it."
        except Exception as e:
            status.error = str(e)
        
        return status
    
    def process_confluence_page(self) -> list[PRStatus]:
        """Main method to process Confluence page and get PR statuses."""
        print(f"\n{'='*70}")
        print("Confluence PR Status Extractor")
        print(f"{'='*70}")
        print(f"Confluence URL: {self.confluence_url}")
        
        # Step 1: Fetch Confluence page
        print(f"\n📄 Fetching Confluence page...")
        success, content = self.fetch_confluence_page()
        
        if not success:
            print(f"❌ {content}")
            return []
        
        print(f"   ✅ Page fetched successfully")
        
        # Step 2: Extract PR links
        print(f"\n🔍 Extracting PR links...")
        pr_links = self.extract_pr_links(content)
        
        if not pr_links:
            print("   ⚠️  No GitHub PR links found on the page")
            return []
        
        print(f"   ✅ Found {len(pr_links)} PR(s)")
        
        # Step 3: Get status for each PR
        print(f"\n📊 Checking PR statuses...")
        print("-" * 70)
        
        for url, repo, pr_number in pr_links:
            print(f"\n   PR #{pr_number} ({repo})")
            status = self.get_pr_status_gh_cli(repo, pr_number)
            self.pr_statuses.append(status)
            
            if status.error:
                print(f"      ❌ Error: {status.error}")
            else:
                # State indicator
                state_icon = {
                    PRState.MERGED: "🟣 MERGED",
                    PRState.CLOSED: "🔴 CLOSED",
                    PRState.OPEN: "🟢 OPEN",
                    PRState.UNKNOWN: "⚪ UNKNOWN"
                }.get(status.state, "⚪ UNKNOWN")
                
                # Review indicator
                review_icon = {
                    ReviewState.APPROVED: "✅ Approved",
                    ReviewState.CHANGES_REQUESTED: "🔄 Changes Requested",
                    ReviewState.REVIEW_REQUIRED: "👀 Review Required",
                    ReviewState.PENDING: "⏳ Pending Review"
                }.get(status.review_state, "❓ Unknown")
                
                # Checks indicator
                if status.checks_total == 0:
                    checks_icon = "➖ No checks"
                elif status.checks_passed:
                    checks_icon = f"✅ All {status.checks_total} checks passed"
                elif status.checks_pending > 0:
                    checks_icon = f"⏳ {status.checks_pending} pending, {status.checks_success} passed, {status.checks_failed} failed"
                else:
                    checks_icon = f"❌ {status.checks_failed} failed, {status.checks_success} passed"
                
                print(f"      Title: {status.title[:50]}...")
                print(f"      State: {state_icon}")
                print(f"      Review: {review_icon} ({status.approvals_count} approvals)")
                print(f"      Checks: {checks_icon}")
        
        return self.pr_statuses
    
    def generate_report(self) -> str:
        """Generate a detailed markdown report."""
        lines = [
            "# Confluence PR Status Report",
            "",
            f"**Generated:** {datetime.now().isoformat()}",
            f"**Source:** {self.confluence_url}",
            "",
            "## Summary",
            "",
            f"- **Total PRs Found:** {len(self.pr_statuses)}",
        ]
        
        # Count by state
        merged = sum(1 for p in self.pr_statuses if p.state == PRState.MERGED)
        open_prs = sum(1 for p in self.pr_statuses if p.state == PRState.OPEN)
        closed = sum(1 for p in self.pr_statuses if p.state == PRState.CLOSED)
        
        lines.extend([
            f"- **Merged:** {merged}",
            f"- **Open:** {open_prs}",
            f"- **Closed:** {closed}",
        ])
        
        # Count by review state (for open PRs)
        approved = sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.review_state == ReviewState.APPROVED)
        changes_requested = sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.review_state == ReviewState.CHANGES_REQUESTED)
        pending_review = sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.review_state in [ReviewState.PENDING, ReviewState.REVIEW_REQUIRED])
        
        lines.extend([
            "",
            "### Open PR Review Status",
            f"- **Approved:** {approved}",
            f"- **Changes Requested:** {changes_requested}",
            f"- **Pending Review:** {pending_review}",
        ])
        
        # Count by checks (for open PRs)
        checks_passed = sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.checks_passed)
        checks_failed = sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.checks_failed > 0)
        checks_pending = sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.checks_pending > 0 and p.checks_failed == 0)
        
        lines.extend([
            "",
            "### Open PR Check Status",
            f"- **All Checks Passed:** {checks_passed}",
            f"- **Checks Failed:** {checks_failed}",
            f"- **Checks Pending:** {checks_pending}",
            "",
        ])
        
        # Detailed table
        lines.extend([
            "## PR Details",
            "",
            "| PR | Title | State | Review | Checks |",
            "|---|---|---|---|---|"
        ])
        
        for pr in self.pr_statuses:
            state_icon = {
                PRState.MERGED: "🟣 Merged",
                PRState.CLOSED: "🔴 Closed",
                PRState.OPEN: "🟢 Open",
                PRState.UNKNOWN: "⚪ Unknown"
            }.get(pr.state, "⚪")
            
            review_icon = {
                ReviewState.APPROVED: "✅ Approved",
                ReviewState.CHANGES_REQUESTED: "🔄 Changes",
                ReviewState.REVIEW_REQUIRED: "👀 Required",
                ReviewState.PENDING: "⏳ Pending"
            }.get(pr.review_state, "❓")
            
            if pr.checks_total == 0:
                checks_str = "➖ None"
            elif pr.checks_passed:
                checks_str = f"✅ {pr.checks_total}/{pr.checks_total}"
            else:
                checks_str = f"{'❌' if pr.checks_failed else '⏳'} {pr.checks_success}/{pr.checks_total}"
            
            title = pr.title[:40] + "..." if len(pr.title) > 40 else pr.title
            lines.append(f"| [#{pr.number}]({pr.url}) | {title} | {state_icon} | {review_icon} | {checks_str} |")
        
        lines.append("")
        
        # Detailed check results
        lines.extend([
            "## Detailed Check Results",
            ""
        ])
        
        for pr in self.pr_statuses:
            if pr.error:
                lines.extend([
                    f"### PR #{pr.number} - Error",
                    f"```",
                    pr.error,
                    f"```",
                    ""
                ])
                continue
            
            state_icon = {
                PRState.MERGED: "🟣",
                PRState.CLOSED: "🔴",
                PRState.OPEN: "🟢",
            }.get(pr.state, "⚪")
            
            lines.extend([
                f"### {state_icon} PR #{pr.number}: {pr.title}",
                "",
                f"- **URL:** {pr.url}",
                f"- **Author:** {pr.author}",
                f"- **State:** {pr.state.value}",
                f"- **Draft:** {'Yes' if pr.draft else 'No'}",
                ""
            ])
            
            # Reviews
            if pr.reviews:
                lines.append("**Reviews:**")
                for review in pr.reviews:
                    review_icon = {
                        ReviewState.APPROVED: "✅",
                        ReviewState.CHANGES_REQUESTED: "🔄",
                        ReviewState.PENDING: "⏳"
                    }.get(review.state, "❓")
                    lines.append(f"- {review_icon} {review.reviewer}: {review.state.value}")
                lines.append("")
            
            # Checks
            if pr.checks:
                lines.append("**Checks:**")
                lines.extend([
                    "| Check | Status |",
                    "|---|---|"
                ])
                for check in pr.checks:
                    check_icon = {
                        CheckStatus.SUCCESS: "✅",
                        CheckStatus.FAILURE: "❌",
                        CheckStatus.PENDING: "⏳",
                        CheckStatus.ERROR: "⚠️",
                        CheckStatus.NEUTRAL: "➖",
                        CheckStatus.SKIPPED: "⏭️"
                    }.get(check.status, "❓")
                    lines.append(f"| {check.name} | {check_icon} {check.status.value} |")
                lines.append("")
            else:
                lines.append("*No CI checks configured*")
                lines.append("")
        
        return "\n".join(lines)
    
    def generate_json_report(self) -> str:
        """Generate a JSON report for programmatic use."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "source_url": self.confluence_url,
            "summary": {
                "total": len(self.pr_statuses),
                "by_state": {
                    "merged": sum(1 for p in self.pr_statuses if p.state == PRState.MERGED),
                    "open": sum(1 for p in self.pr_statuses if p.state == PRState.OPEN),
                    "closed": sum(1 for p in self.pr_statuses if p.state == PRState.CLOSED),
                },
                "open_prs": {
                    "approved": sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.review_state == ReviewState.APPROVED),
                    "changes_requested": sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.review_state == ReviewState.CHANGES_REQUESTED),
                    "pending_review": sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.review_state in [ReviewState.PENDING, ReviewState.REVIEW_REQUIRED]),
                    "checks_passed": sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.checks_passed),
                    "checks_failed": sum(1 for p in self.pr_statuses if p.state == PRState.OPEN and p.checks_failed > 0),
                }
            },
            "pull_requests": []
        }
        
        for pr in self.pr_statuses:
            pr_data = {
                "number": pr.number,
                "url": pr.url,
                "repo": pr.repo,
                "title": pr.title,
                "author": pr.author,
                "state": pr.state.value,
                "draft": pr.draft,
                "review": {
                    "state": pr.review_state.value,
                    "approvals": pr.approvals_count,
                    "reviews": [
                        {"reviewer": r.reviewer, "state": r.state.value}
                        for r in pr.reviews
                    ]
                },
                "checks": {
                    "passed": pr.checks_passed,
                    "total": pr.checks_total,
                    "success": pr.checks_success,
                    "failed": pr.checks_failed,
                    "pending": pr.checks_pending,
                    "details": [
                        {"name": c.name, "status": c.status.value}
                        for c in pr.checks
                    ]
                }
            }
            if pr.error:
                pr_data["error"] = pr.error
            
            report["pull_requests"].append(pr_data)
        
        return json.dumps(report, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Extract GitHub PR links from a Confluence page and report their status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage
  python confluence_pr_extractor.py "https://mycompany.atlassian.net/wiki/spaces/DEV/pages/123456/Release+PRs"

  # With Confluence authentication
  python confluence_pr_extractor.py -u user@example.com -t API_TOKEN "https://..."

  # Output as JSON
  python confluence_pr_extractor.py --json "https://..."

  # Save report to file
  python confluence_pr_extractor.py -o report.md "https://..."

Environment Variables:
  CONFLUENCE_USER   - Confluence username/email
  CONFLUENCE_TOKEN  - Confluence API token or password
  GITHUB_TOKEN      - GitHub token (optional, uses gh CLI auth)
        """
    )
    
    parser.add_argument(
        "url",
        help="Confluence page URL containing PR links"
    )
    
    parser.add_argument(
        "-u", "--user",
        help="Confluence username or email"
    )
    
    parser.add_argument(
        "-t", "--token",
        help="Confluence API token or password"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: stdout)"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of markdown"
    )
    
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output"
    )
    
    args = parser.parse_args()
    
    # Suppress output if quiet mode
    if args.quiet:
        sys.stdout = open(os.devnull, 'w')
    
    # Create extractor
    extractor = ConfluencePRExtractor(
        confluence_url=args.url,
        confluence_user=args.user,
        confluence_token=args.token
    )
    
    # Process page
    extractor.process_confluence_page()
    
    # Restore stdout
    if args.quiet:
        sys.stdout = sys.__stdout__
    
    # Generate report
    if args.json:
        report = extractor.generate_json_report()
    else:
        report = extractor.generate_report()
    
    # Output
    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"\n📄 Report saved to: {args.output}")
    else:
        print("\n" + "=" * 70)
        print(report)
    
    # Exit with error if any PRs had errors
    if any(pr.error for pr in extractor.pr_statuses):
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
