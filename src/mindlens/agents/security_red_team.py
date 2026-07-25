"""Security Red Team — scans for security vulnerabilities and creates GitHub issues."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from mindlens.agents.base import Agent, AgentContext, AgentResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Security Red Team agent of MindLens Cortex.

You check the entire MindLens project for security issues:

1. **Secrets in code** — API keys, tokens, passwords hardcoded
2. **Injection vulnerabilities** — SQL injection, command injection, path traversal
3. **Authentication issues** — missing auth checks, weak validation
4. **Dependency vulnerabilities** — outdated packages, known CVEs
5. **Configuration issues** — debug mode in production, verbose errors
6. **Data exposure** — sensitive data in logs, error messages, responses
7. **Telegram security** — user ID validation, message injection
8. **File system security** — path traversal, symlink attacks

Always respond in the same language as the user's message with a JSON array of found issues:
[
    {
        "title": "short description",
        "description": "detailed description with location and impact",
        "severity": "critical|high|medium|low",
        "category": "secrets|injection|auth|deps|config|exposure|filesystem",
        "file": "path to file",
        "line": 123,
        "labels": ["security", "auto-detected"],
        "suggested_fix": "how to fix"
    }
]

Be thorough but not paranoid. Only real issues, not theoretical risks.
"""


class SecurityRedTeam(Agent):
    name = "security_red_team"
    description = "Security scanning — detects vulnerabilities and creates GitHub issues"
    scope = "global"

    async def run(self, context: AgentContext) -> AgentResult:
        task = context.task.lower()

        if "full" in task or "complete" in task:
            return await self._full_scan()
        elif "quick" in task:
            return await self._quick_scan()
        elif "secret" in task or "key" in task or "token" in task:
            return await self._scan_secrets()
        elif "issue" in task or "github" in task:
            return await self._scan_and_create_issues()
        else:
            return await self._quick_scan()

    async def _quick_scan(self) -> AgentResult:
        """Quick scan — check most common issues."""
        findings = []

        # 1. Scan for hardcoded secrets
        secrets = self._find_secrets()
        if secrets:
            findings.append("## Possible secrets in code\n")
            for s in secrets[:10]:
                findings.append(f"- {s['file']}:{s['line']} — {s['match'][:60]}")

        # 2. Check .env.example for leaked values
        env_example = self._check_env_example()
        if env_example:
            findings.append("\n## .env.example problemen\n")
            for e in env_example:
                findings.append(f"- {e}")

        # 3. Check .gitignore completeness
        gitignore = self._check_gitignore()
        if gitignore:
            findings.append("\n## .gitignore missing entries\n")
            for g in gitignore:
                findings.append(f"- {g}")

        if not findings:
            return AgentResult(success=True, output="✅ Quick scan: no security issues found.")

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Analyze these security findings:\n\n{''.join(findings)}",
            temperature=0.2,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

    async def _full_scan(self) -> AgentResult:
        """Full scan — all checks."""
        findings = []

        # All quick scan checks
        secrets = self._find_secrets()
        if secrets:
            findings.append("## Secrets\n")
            for s in secrets[:15]:
                findings.append(f"- {s['file']}:{s['line']} — {s['match'][:60]}")

        # Python-specific checks
        py_issues = self._scan_python_code()
        if py_issues:
            findings.append("\n## Python code issues\n")
            for p in py_issues[:15]:
                findings.append(f"- {p['file']}:{p['line']} — {p['issue']}")

        # Dependency check
        deps = self._check_dependencies()
        if deps:
            findings.append("\n## Dependency issues\n")
            for d in deps:
                findings.append(f"- {d}")

        # Config check
        config = self._check_config()
        if config:
            findings.append("\n## Configuration issues\n")
            for c in config:
                findings.append(f"- {c}")

        if not findings:
            return AgentResult(success=True, output="✅ Full scan: no security issues found.")

        content, in_tok, out_tok = await self._llm_complete(
            SYSTEM_PROMPT,
            f"Analyze this full security scan:\n\n{''.join(findings)}",
            temperature=0.2,
        )

        return AgentResult(success=True, output=content, input_tokens=in_tok, output_tokens=out_tok)

    async def _scan_secrets(self) -> AgentResult:
        """Scan specifically for secrets and credentials."""
        secrets = self._find_secrets()

        if not secrets:
            return AgentResult(success=True, output="✅ No hardcoded secrets found.")

        output = "🔐 Possible secrets found:\n\n"
        for s in secrets:
            output += f"• `{s['file']}:{s['line']}` — {s['match'][:80]}\n"

        return AgentResult(success=True, output=output)

    async def _scan_and_create_issues(self) -> AgentResult:
        """Full scan + create GitHub issues for findings."""
        # Run full scan
        scan_result = await self._full_scan()

        if "no security issues" in scan_result.output.lower():
            return scan_result

        # Parse issues from LLM response
        cleaned = self._strip_code_fences(scan_result.output)
        try:
            issues = json.loads(cleaned)
        except json.JSONDecodeError:
            return AgentResult(
                success=True,
                output=f"Security scan result (not structured):\n\n{scan_result.output[:500]}",
                input_tokens=scan_result.input_tokens,
                output_tokens=scan_result.output_tokens,
            )

        if not isinstance(issues, list):
            issues = [issues]

        # Create GitHub issues
        created = []
        for issue in issues:
            title = f"[Security] {issue.get('title', 'Security issue')}"
            body = f"## Security Issue (auto-detected)\n\n{issue.get('description', '')}\n\n"
            body += f"**Severity:** {issue.get('severity', 'medium')}\n"
            body += f"**Category:** {issue.get('category', 'unknown')}\n"
            if issue.get("file"):
                body += f"**Location:** `{issue['file']}`"
                if issue.get("line"):
                    body += f":{issue['line']}"
                body += "\n"
            if issue.get("suggested_fix"):
                body += f"\n## Suggested fix\n\n{issue['suggested_fix']}\n"
            body += "\n---\n*Auto-detected by MindLens Security Red Team*\n"

            labels = issue.get("labels", ["security", "auto-detected"])
            url = self._create_github_issue(title, body, labels)
            if url:
                created.append(f"✅ [{issue.get('title', '?')}]({url})")
            else:
                created.append(f"❌ {issue.get('title', '?')} (creation failed)")

        output = f"🛡️ Security Red Team Resultaat:\n\n"
        output += f"**{len(created)} issues gevonden en verwerkt:**\n\n"
        for c in created:
            output += f"  {c}\n"

        return AgentResult(
            success=True, output=output,
            input_tokens=scan_result.input_tokens, output_tokens=scan_result.output_tokens,
        )

    # --- Scan helpers ---

    def _find_secrets(self) -> list[dict]:
        """Find potential hardcoded secrets in the codebase."""
        project = self.config.project_path
        if not project.exists():
            return []

        patterns = [
            (r'(?:api[_-]?key|secret|token|password)\s*[=:]\s*["\'][^"\']{8,}', "Possible secret"),
            (r'sk-or-v1-[a-zA-Z0-9]{20,}', "OpenRouter API key"),
            (r'glpat-[a-zA-Z0-9]{20,}', "GitLab token"),
            (r'ghp_[a-zA-Z0-9]{20,}', "GitHub token"),
            (r'(?:Bearer|Basic)\s+[a-zA-Z0-9+/=]{20,}', "Auth header"),
        ]

        findings = []
        src = project / "src"
        if not src.exists():
            return []

        for py_file in src.rglob("*.py"):
            try:
                content = py_file.read_text()
                for line_num, line in enumerate(content.splitlines(), 1):
                    # Skip comments
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    for pattern, desc in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            findings.append({
                                "file": str(py_file.relative_to(project)),
                                "line": line_num,
                                "match": stripped[:100],
                                "description": desc,
                            })
            except Exception:
                continue

        return findings

    def _check_env_example(self) -> list[str]:
        """Check .env.example for issues."""
        project = self.config.project_path
        issues = []

        env_example = project / ".env.example"
        if not env_example.exists():
            issues.append(".env.example not found — users don't know which variables are needed")
            return issues

        content = env_example.read_text()
        # Check for real values (not placeholders)
        if re.search(r'sk-or-v1-[a-zA-Z0-9]{20,}', content):
            issues.append("Possible real API key in .env.example!")
        if "8757887592" in content:
            issues.append("Real Telegram token in .env.example!")

        return issues

    def _check_gitignore(self) -> list[str]:
        """Check .gitignore completeness."""
        project = self.config.project_path
        issues = []

        gitignore = project / ".gitignore"
        if not gitignore.exists():
            issues.append(".gitignore not found!")
            return issues

        content = gitignore.read_text()
        required = [".env", "*.db", "__pycache__", ".venv", ".DS_Store"]
        for r in required:
            if r not in content:
                issues.append(f"Missing in .gitignore: `{r}`")

        return issues

    def _scan_python_code(self) -> list[dict]:
        """Scan Python code for common security issues."""
        project = self.config.project_path
        issues = []

        patterns = [
            (r'eval\s*\(', "eval() usage — potential code injection"),
            (r'exec\s*\(', "exec() usage — potential code injection"),
            (r'subprocess\.(?:call|run|Popen)\s*\(.*shell\s*=\s*True', "shell=True — command injection risk"),
            (r'os\.system\s*\(', "os.system() — use subprocess instead"),
            (r'pickle\.load', "pickle.load — deserialization risk"),
            (r'yaml\.load\s*\([^)]*\)', "yaml.load without SafeLoader"),
            (r'open\s*\([^)]*["\']w["\'].*\+.*["\']r["\']', "File opened for read+write unexpectedly"),
        ]

        src = project / "src"
        if not src.exists():
            return issues

        for py_file in src.rglob("*.py"):
            try:
                content = py_file.read_text()
                for line_num, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    for pattern, desc in patterns:
                        if re.search(pattern, line):
                            issues.append({
                                "file": str(py_file.relative_to(project)),
                                "line": line_num,
                                "issue": desc,
                            })
            except Exception:
                continue

        return issues

    def _check_dependencies(self) -> list[str]:
        """Check for dependency issues."""
        project = self.config.project_path
        issues = []

        pyproject = project / "pyproject.toml"
        if pyproject.exists():
            content = pyproject.read_text()
            # Check for unpinned versions
            if ">=" in content and "==" not in content:
                issues.append("Dependencies use >= without pinning — consider exact versions for reproducibility")

        return issues

    def _check_config(self) -> list[str]:
        """Check configuration issues."""
        project = self.config.project_path
        issues = []

        # Check if .env is in git
        try:
            result = subprocess.run(
                ["git", "ls-files", ".env"],
                capture_output=True, text=True, cwd=str(project),
            )
            if ".env" in result.stdout:
                issues.append("CRITICAL: .env is tracked by git!")
        except Exception:
            pass

        return issues

    def _create_github_issue(self, title: str, body: str, labels: list[str]) -> str | None:
        """Create a GitHub issue using gh CLI."""
        try:
            result = subprocess.run(
                ["gh", "issue", "create",
                 "--title", title,
                 "--body", body,
                 "--label", ",".join(labels)],
                capture_output=True, text=True, timeout=30,
                cwd=str(self.config.project_path),
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                logger.info("Created security issue: %s", url)
                return url
            else:
                logger.error("Failed to create issue: %s", result.stderr)
                return None
        except Exception as e:
            logger.error("Failed to create issue: %s", e)
            return None
