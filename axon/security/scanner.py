"""Safe, explainable URL phishing-risk triage helpers.

This module intentionally does not fetch the submitted URL or claim to identify
phishing conclusively. It evaluates structural signals and, for public targets
only, performs limited DNS, TLS, and RDAP checks.
"""

import ipaddress
import re
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import unquote_plus, urlsplit

import requests


SUSPICIOUS_WORDS = {
    "login", "verify", "verification", "secure", "account", "update",
    "wallet", "password", "signin", "confirm", "unlock", "gift", "bonus",
}
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_TOKEN = re.compile(r"[a-z0-9]+")


def _invalid(reason):
    return f"Invalid URL: {reason}"


def _is_public_ip(address):
    """Return whether *address* is publicly routable, including IPv6 checks."""
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def _normalise_url(value):
    """Validate input and return (parts, unicode_host, ascii_host, is_ip)."""
    if not isinstance(value, str):
        return None, _invalid("enter a domain or HTTP(S) URL.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None, _invalid("control characters are not allowed.")
    raw = value.strip()
    if not raw:
        return None, _invalid("enter a domain or HTTP(S) URL.")

    # A colon in the first URI component means the caller supplied a scheme.
    # Do not turn e.g. mailto: or javascript: into an HTTPS hostname.
    try:
        supplied = urlsplit(raw)
    except ValueError:
        return None, _invalid("the host or port is malformed.")
    if supplied.scheme:
        if supplied.scheme.lower() not in {"http", "https"}:
            return None, _invalid("only HTTP and HTTPS URLs are supported.")
        candidate = raw
    else:
        candidate = "https://" + raw

    try:
        parts = urlsplit(candidate)
        _ = parts.port  # validates malformed and out-of-range port values
        host = parts.hostname
    except ValueError:
        return None, _invalid("the host or port is malformed.")
    if not parts.netloc or not host:
        return None, _invalid("no valid domain detected.")

    host = host.rstrip(".").lower()
    if not host:
        return None, _invalid("no valid domain detected.")
    try:
        ascii_host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None, _invalid("the hostname is not valid IDNA.")

    try:
        ipaddress.ip_address(ascii_host)
        is_ip = True
    except ValueError:
        is_ip = False
        labels = ascii_host.split(".")
        if any(not _HOST_LABEL.fullmatch(label) for label in labels):
            return None, _invalid("the hostname is malformed.")
    return (parts, host, ascii_host, is_ip), None


def _tokens(text):
    return set(_TOKEN.findall(unquote_plus(text).lower()))


def _public_addresses(host):
    """Resolve once, retaining only public IPv4/IPv6 addresses."""
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return [], "DNS lookup unavailable"
    addresses = []
    for record in records:
        address = record[4][0]
        if _is_public_ip(address) and address not in addresses:
            addresses.append(address)
    if not addresses:
        return [], "DNS did not return a public address"
    return addresses, None


def _probe_tls(address, hostname):
    """Verify TLS against a checked address while retaining hostname SNI."""
    try:
        with socket.create_connection((address, 443), timeout=2) as connection:
            context = ssl.create_default_context()
            with context.wrap_socket(connection, server_hostname=hostname) as secure:
                secure.getpeercert()
        return True
    except (OSError, ssl.SSLError, ValueError):
        return False


def _domain_age(host):
    """Return (age_in_days, unknown_message) without treating failure as risk."""
    try:
        response = requests.get(
            f"https://rdap.org/domain/{host}", timeout=4,
            headers={"User-Agent": "AXON-Sentinel/14.0"}, allow_redirects=False,
        )
        if not response.ok:
            return None, "RDAP registration data unavailable"
        events = response.json().get("events", [])
        for event in events:
            if event.get("eventAction") in {"registration", "creation"}:
                registered = event.get("eventDate")
                if registered:
                    date = datetime.fromisoformat(registered.replace("Z", "+00:00"))
                    return max(0, (datetime.now(timezone.utc) - date).days), None
        return None, "Domain registration date unavailable"
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None, "Domain age lookup unavailable"


def analyze_url(value):
    """Return an evidence-based heuristic phishing-risk assessment for a URL."""
    normalised, error = _normalise_url(value)
    if error:
        return error
    parts, unicode_host, host, is_ip = normalised
    score = 0
    evidence = []
    unknown = []
    confirmed = 0

    def add(points, message):
        nonlocal score
        score += points
        evidence.append(f"⚠ {message}")

    if parts.scheme == "https":
        evidence.append("✓ HTTPS was requested")
    else:
        add(5, "HTTP is used instead of HTTPS")
    if parts.username is not None:
        add(20, "URL credentials can obscure the real destination")
    if is_ip:
        add(20, "An IP address is used instead of a domain")
    else:
        labels = host.split(".")
        if any(label.startswith("xn--") for label in labels):
            add(10, "Punycode / internationalized domain encoding is present")
        if len(labels) > 4:
            add(10, "Many subdomain levels are present")
        if len(host) > 55:
            add(6, "The hostname is unusually long")
        hostname_terms = _tokens(host.replace(".", " ").replace("-", " ")) & SUSPICIOUS_WORDS
        if hostname_terms:
            add(min(18, len(hostname_terms) * 6), "Suspicious terms appear in hostname labels")
    path_query_terms = _tokens(f"{parts.path} {parts.query}") & SUSPICIOUS_WORDS
    if path_query_terms:
        add(min(12, len(path_query_terms) * 4), "Suspicious terms appear in the path or query")

    prohibited = (
        host == "localhost" or host.endswith(".localhost") or host.endswith(".local")
        or (is_ip and not _is_public_ip(host))
    )
    addresses = []
    if prohibited:
        unknown.append("Network checks were skipped because the target is not public")
    elif is_ip:
        addresses = [host]
    else:
        addresses, dns_unknown = _public_addresses(host)
        if dns_unknown:
            unknown.append(dns_unknown)

    if addresses:
        confirmed += 1
        evidence.append(f"✓ DNS/public-address validation found {len(addresses)} public address(es)")
        if parts.scheme == "https":
            if _probe_tls(addresses[0], host):
                confirmed += 1
                evidence.append("✓ TLS certificate was verified for the hostname")
            else:
                unknown.append("TLS certificate verification was unavailable")
        # IP registrations are not domain registrations, so RDAP is skipped for
        # literal-IP targets. A resolved public hostname is safe to query.
        if not is_ip:
            age, age_unknown = _domain_age(host)
            if age is None:
                unknown.append(age_unknown)
            elif age < 30:
                add(20, f"Domain was registered about {age} days ago")
                confirmed += 1
            elif age < 180:
                add(10, f"Domain is relatively new ({age} days)")
                confirmed += 1
            else:
                evidence.append(f"✓ Domain age: about {age} days")
                confirmed += 1

    score = min(100, score)
    risk = "HIGH" if score >= 55 else "MEDIUM" if score >= 25 else "LOW"
    if unknown:
        confidence = "LOW" if confirmed == 0 else "MEDIUM"
    else:
        confidence = "HIGH" if confirmed >= 3 else "MEDIUM"
    result = (
        f"DOMAIN: {unicode_host}\n\nRISK: {risk}  ·  SCORE: {score}/100\n"
        f"CONFIDENCE: {confidence}\n\nEVIDENCE\n"
        + "\n".join(evidence or ["No structural evidence was collected."])
    )
    if unknown:
        result += "\n\nUNKNOWN SIGNALS\n" + "\n".join(f"? {item}" for item in unknown)
    return result + (
        "\n\nThis is a heuristic phishing-risk assessment, not a definitive phishing "
        "or safety determination."
    )
