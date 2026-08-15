"""Multi-source URL threat intelligence for AXON Sentinel.

The module is deliberately conservative: absence from a threat feed is never
reported as proof that a URL is safe. It combines structural heuristics with
optional Google Safe Browsing v5, VirusTotal, urlscan.io and PhishTank checks.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

from .security.scanner import _normalise_url, analyze_url


@dataclass
class SourceResult:
    name: str
    status: str = "NOT CONFIGURED"
    verdict: str = "UNKNOWN"
    detail: str = ""
    evidence: list[str] = field(default_factory=list)


def _request(method, url, **kwargs):
    kwargs.setdefault("timeout", 8)
    kwargs.setdefault("headers", {})
    kwargs["headers"].setdefault("User-Agent", "AXON-Sentinel/15.6")
    return requests.request(method, url, **kwargs)


def google_safe_browsing(url: str, api_key: str) -> SourceResult:
    if not api_key:
        return SourceResult("Google Safe Browsing")
    try:
        endpoint = "https://safebrowsing.googleapis.com/v5/urls:search"
        response = _request("GET", endpoint, params={"key": api_key, "urls": url})
        if response.status_code != 200:
            return SourceResult("Google Safe Browsing", "ERROR", "UNKNOWN", f"HTTP {response.status_code}")
        threats = response.json().get("threats", [])
        if threats:
            types = sorted({t for item in threats for t in item.get("threatTypes", [])})
            return SourceResult("Google Safe Browsing", "ONLINE", "MALICIOUS", ", ".join(types), ["Known threat match: " + ", ".join(types)])
        return SourceResult("Google Safe Browsing", "ONLINE", "NO_MATCH", "No known Safe Browsing threat match")
    except Exception as exc:
        return SourceResult("Google Safe Browsing", "ERROR", "UNKNOWN", str(exc)[:180])


def virustotal(url: str, api_key: str) -> SourceResult:
    if not api_key:
        return SourceResult("VirusTotal")
    try:
        url_id = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        endpoint = f"https://www.virustotal.com/api/v3/urls/{url_id}"
        response = _request("GET", endpoint, headers={"x-apikey": api_key, "User-Agent": "AXON-Sentinel/15.6"})
        if response.status_code == 404:
            return SourceResult("VirusTotal", "ONLINE", "NO_REPORT", "No existing URL report")
        if response.status_code != 200:
            return SourceResult("VirusTotal", "ERROR", "UNKNOWN", f"HTTP {response.status_code}")
        stats = response.json().get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
        malicious = int(stats.get("malicious", 0) or 0)
        suspicious = int(stats.get("suspicious", 0) or 0)
        total = sum(int(v or 0) for v in stats.values() if isinstance(v, (int, float)))
        if malicious:
            return SourceResult("VirusTotal", "ONLINE", "MALICIOUS", f"{malicious} malicious / {total} engines", [f"{malicious} engines marked the URL malicious"])
        if suspicious:
            return SourceResult("VirusTotal", "ONLINE", "SUSPICIOUS", f"{suspicious} suspicious / {total} engines", [f"{suspicious} engines marked the URL suspicious"])
        return SourceResult("VirusTotal", "ONLINE", "NO_DETECTION", f"0 malicious / {total} engines")
    except Exception as exc:
        return SourceResult("VirusTotal", "ERROR", "UNKNOWN", str(exc)[:180])


def urlscan(url: str, api_key: str) -> SourceResult:
    if not api_key:
        return SourceResult("urlscan.io")
    try:
        query = f'page.url:"{url}"'
        endpoint = "https://urlscan.io/api/v1/search/"
        response = _request("GET", endpoint, params={"q": query, "size": 5}, headers={"API-Key": api_key, "User-Agent": "AXON-Sentinel/15.6"})
        if response.status_code != 200:
            return SourceResult("urlscan.io", "ERROR", "UNKNOWN", f"HTTP {response.status_code}")
        results = response.json().get("results", [])
        if not results:
            return SourceResult("urlscan.io", "ONLINE", "NO_REPORT", "No historical scan found")
        malicious = 0
        suspicious = 0
        for item in results:
            verdicts = item.get("verdicts", {}) or {}
            us = verdicts.get("urlscan", {}) or {}
            community = verdicts.get("community", {}) or {}
            if us.get("malicious") is True:
                malicious += 1
            score = community.get("score")
            if isinstance(score, (int, float)) and score < 0:
                suspicious += 1
        if malicious:
            return SourceResult("urlscan.io", "ONLINE", "MALICIOUS", f"{malicious} historical scan(s) flagged malicious", ["urlscan malicious verdict present"])
        if suspicious:
            return SourceResult("urlscan.io", "ONLINE", "SUSPICIOUS", f"{suspicious} historical scan(s) have negative community scores")
        return SourceResult("urlscan.io", "ONLINE", "NO_MALICIOUS_VERDICT", f"{len(results)} historical scan(s) reviewed")
    except Exception as exc:
        return SourceResult("urlscan.io", "ERROR", "UNKNOWN", str(exc)[:180])


def phishtank(url: str, app_key: str = "") -> SourceResult:
    try:
        data = {"url": url, "format": "json"}
        if app_key:
            data["app_key"] = app_key
        response = _request("POST", "https://checkurl.phishtank.com/checkurl/", data=data)
        if response.status_code != 200:
            return SourceResult("PhishTank", "ERROR", "UNKNOWN", f"HTTP {response.status_code}")
        result = response.json().get("results", {})
        if result.get("in_database") and result.get("verified") and result.get("valid"):
            pid = result.get("phish_id", "unknown")
            return SourceResult("PhishTank", "ONLINE", "MALICIOUS", f"Verified active phishing record #{pid}", [f"Verified phishing record #{pid}"])
        if result.get("in_database"):
            return SourceResult("PhishTank", "ONLINE", "SUSPICIOUS", "URL exists in PhishTank but is not currently verified active")
        return SourceResult("PhishTank", "ONLINE", "NO_MATCH", "No matching phishing record")
    except Exception as exc:
        return SourceResult("PhishTank", "ERROR", "UNKNOWN", str(exc)[:180])


def _heuristic_bonus(url: str) -> tuple[int, list[str]]:
    parsed, error = _normalise_url(url)
    if error:
        return 0, []
    parts, _, host, is_ip = parsed
    score = 0
    evidence = []
    labels = host.split(".")
    registrable = ".".join(labels[-2:]) if len(labels) >= 2 else host
    core = labels[-2] if len(labels) >= 2 else labels[0]
    brands = {"paypal", "microsoft", "office365", "outlook", "google", "gmail", "apple", "icloud", "facebook", "instagram", "whatsapp", "amazon", "netflix", "linkedin", "coinbase", "binance", "metamask", "docusign", "dropbox", "github"}
    brand_hits = [b for b in brands if b in labels[:-2] or (b in core and core != b)]
    if brand_hits:
        score += 18
        evidence.append("Possible brand impersonation in hostname: " + ", ".join(sorted(brand_hits)))
    tld = "." + labels[-1] if labels else ""
    risky_tlds = {".top", ".click", ".xyz", ".icu", ".shop", ".live", ".support", ".cam", ".buzz", ".win", ".loan", ".download", ".zip", ".mov"}
    if tld in risky_tlds:
        score += 8
        evidence.append(f"Higher-abuse-risk TLD observed: {tld}")
    if len(parts.path) > 120:
        score += 6
        evidence.append("Unusually long URL path")
    if parts.query and len(parts.query) > 180:
        score += 6
        evidence.append("Unusually large query string")
    if is_ip:
        score += 15
        evidence.append("Direct IP address destination")
    return score, evidence


def deep_analyze_url(url: str, credentials: dict | None = None) -> str:
    credentials = credentials or {}
    base = analyze_url(url)
    if base.startswith("Invalid URL:"):
        return base
    parsed, error = _normalise_url(url)
    if error:
        return error
    parts, unicode_host, host, _ = parsed
    normalized = parts.geturl()

    results = [
        google_safe_browsing(normalized, credentials.get("google_safe_browsing", "")),
        virustotal(normalized, credentials.get("virustotal", "")),
        urlscan(normalized, credentials.get("urlscan", "")),
        phishtank(normalized, credentials.get("phishtank", "")),
    ]
    bonus, bonus_evidence = _heuristic_bonus(normalized)
    # Extract the legacy score without parsing every line; only the explicit
    # heuristic score is used as a supporting signal.
    match = __import__("re").search(r"SCORE: (\d+)/100", base)
    heuristic = int(match.group(1)) if match else 0
    combined = min(100, heuristic + bonus)
    malicious = [r for r in results if r.verdict == "MALICIOUS"]
    suspicious = [r for r in results if r.verdict == "SUSPICIOUS"]
    errors = [r for r in results if r.status == "ERROR"]
    configured = [r for r in results if r.status != "NOT CONFIGURED"]

    if malicious:
        verdict = "MALICIOUS / PHISHING"
        confidence = "HIGH" if len(malicious) >= 2 or any(r.name in {"Google Safe Browsing", "PhishTank"} for r in malicious) else "MEDIUM"
    elif len(suspicious) >= 2 or combined >= 70:
        verdict = "HIGH RISK / SUSPICIOUS"
        confidence = "HIGH" if len(suspicious) >= 2 else "MEDIUM"
    elif combined >= 40 or suspicious:
        verdict = "SUSPICIOUS"
        confidence = "MEDIUM"
    elif configured and not errors:
        verdict = "LOW RISK — NO KNOWN THREAT MATCH"
        confidence = "MEDIUM"
    else:
        verdict = "INCONCLUSIVE — NOT PROVEN SAFE"
        confidence = "LOW"

    lines = [
        f"URL: {normalized}",
        "",
        f"VERDICT: {verdict}",
        f"CONFIDENCE: {confidence}  ·  COMBINED RISK: {combined}/100",
        "",
        "THREAT INTELLIGENCE",
    ]
    for result in results:
        lines.append(f"• {result.name}: {result.verdict} — {result.detail or result.status}")
        lines.extend(f"  {item}" for item in result.evidence)
    lines.append("")
    lines.append("LOCAL HEURISTICS")
    lines.extend("• " + line for line in bonus_evidence) if bonus_evidence else lines.append("• No additional local brand/TLD/length indicators.")
    lines.append("")
    lines.append("BASE EVIDENCE")
    for line in base.splitlines():
        if line.startswith("DOMAIN:") or line.startswith("RISK:") or line.startswith("CONFIDENCE:") or line.startswith("EVIDENCE") or line.startswith("⚠") or line.startswith("✓") or line.startswith("UNKNOWN SIGNALS") or line.startswith("?"):
            lines.append(line)
    if errors:
        lines += ["", "SOURCE ERRORS"] + [f"• {r.name}: {r.detail}" for r in errors]
    lines += ["", "IMPORTANT: No clean result proves a URL is safe. AXON reports evidence and confidence, not a guarantee."]
    return "\n".join(lines)
