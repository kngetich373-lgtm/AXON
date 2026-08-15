import socket
import ssl
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import requests

from axon.security import analyze_url


PUBLIC_ADDRESS = "93.184.216.34"
PUBLIC_RECORDS = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_ADDRESS, 443))]


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSecureConnection(FakeConnection):
    def getpeercert(self):
        return {"subject": ((('commonName', 'example.test'),),)}


class FakeSSLContext:
    def wrap_socket(self, connection, server_hostname):
        self.server_hostname = server_hostname
        return FakeSecureConnection()


class FakeResponse:
    def __init__(self, age_days=365, ok=True):
        self.age_days = age_days
        self.ok = ok

    def json(self):
        registered = datetime.now(timezone.utc) - timedelta(days=self.age_days)
        return {"events": [{
            "eventAction": "registration",
            "eventDate": registered.isoformat().replace("+00:00", "Z"),
        }]}


class SecurityAnalyzerTests(unittest.TestCase):
    def analyze_public(self, url, *, response=None, tls_error=False):
        response = response or FakeResponse()
        connection = OSError("TLS unavailable") if tls_error else FakeConnection()
        with patch("axon.security.socket.getaddrinfo", return_value=PUBLIC_RECORDS), \
             patch("axon.security.socket.create_connection", return_value=connection), \
             patch("axon.security.ssl.create_default_context", return_value=FakeSSLContext()), \
             patch("axon.security.requests.get", return_value=response):
            return analyze_url(url)

    def test_valid_https_public_domain_reports_verified_signals(self):
        result = self.analyze_public("HTTPS://Example.COM./welcome")
        self.assertIn("DOMAIN: example.com", result)
        self.assertIn("HTTPS was requested", result)
        self.assertIn("TLS certificate was verified", result)
        self.assertIn("RISK: LOW", result)
        self.assertIn("heuristic phishing-risk assessment", result)

    def test_invalid_and_unsupported_inputs_do_not_reach_network(self):
        with patch("axon.security.socket.getaddrinfo") as resolve, \
             patch("axon.security.socket.create_connection") as connect, \
             patch("axon.security.requests.get") as rdap:
            for value in (
                "", "javascript:alert(1)", "mailto:test@example.com",
                "https://example.com:99999", "https://example.com:notaport",
                "https://example.com/\n", "https://[::1",
            ):
                self.assertTrue(analyze_url(value).startswith("Invalid URL:"), value)
            resolve.assert_not_called()
            connect.assert_not_called()
            rdap.assert_not_called()

    def test_query_email_is_not_credentials_but_userinfo_is(self):
        query_result = self.analyze_public("https://example.com/?email=person@example.net")
        credentials_result = self.analyze_public("https://trusted.example@evil.example/")
        self.assertNotIn("URL credentials can obscure", query_result)
        self.assertIn("URL credentials can obscure", credentials_result)

    def test_public_ipv4_and_ipv6_skip_dns_and_domain_rdap(self):
        for url in ("https://8.8.8.8/login", "https://[2001:4860:4860::8888]/login"):
            with patch("axon.security.socket.getaddrinfo") as resolve, \
                 patch("axon.security.socket.create_connection", return_value=FakeConnection()) as connect, \
                 patch("axon.security.ssl.create_default_context", return_value=FakeSSLContext()), \
                 patch("axon.security.requests.get") as rdap:
                result = analyze_url(url)
                self.assertIn("IP address is used instead of a domain", result)
                resolve.assert_not_called()
                rdap.assert_not_called()
                connect.assert_called_once()

    def test_non_public_targets_never_make_network_calls(self):
        targets = (
            "https://localhost/", "https://127.0.0.1/", "https://192.168.1.10/",
            "https://198.51.100.1/", "https://[::1]/",
        )
        for target in targets:
            with self.subTest(target=target), \
                 patch("axon.security.socket.getaddrinfo") as resolve, \
                 patch("axon.security.socket.create_connection") as connect, \
                 patch("axon.security.requests.get") as rdap:
                result = analyze_url(target)
                self.assertIn("Network checks were skipped", result)
                resolve.assert_not_called()
                connect.assert_not_called()
                rdap.assert_not_called()

    def test_hostname_resolving_only_to_private_ip_is_not_probed(self):
        private_records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))]
        with patch("axon.security.socket.getaddrinfo", return_value=private_records) as resolve, \
             patch("axon.security.socket.create_connection") as connect, \
             patch("axon.security.requests.get") as rdap:
            result = analyze_url("https://internal-looking.example/")
            self.assertIn("DNS did not return a public address", result)
            resolve.assert_called_once()
            connect.assert_not_called()
            rdap.assert_not_called()

    def test_network_failures_are_unknowns_not_phishing_points(self):
        with patch("axon.security.socket.getaddrinfo", return_value=PUBLIC_RECORDS), \
             patch("axon.security.socket.create_connection", side_effect=OSError("no TLS")), \
             patch("axon.security.requests.get", side_effect=requests.RequestException("no RDAP")):
            result = analyze_url("https://ordinary.example/")
        self.assertIn("SCORE: 0/100", result)
        self.assertIn("TLS certificate verification was unavailable", result)
        self.assertIn("Domain age lookup unavailable", result)
        self.assertIn("RISK: LOW", result)

    def test_path_tokens_are_detected_but_substrings_are_not(self):
        suspicious = self.analyze_public("https://example.com/account/verify?next=login")
        harmless = self.analyze_public("https://securely.example/products")
        self.assertIn("Suspicious terms appear in the path or query", suspicious)
        self.assertNotIn("Suspicious terms appear", harmless)

    def test_punycode_deep_subdomains_and_new_domain_raise_risk(self):
        result = self.analyze_public(
            "https://xn--bcher-kva.login.verify.account.example.com/secure",
            response=FakeResponse(age_days=7),
        )
        self.assertIn("Punycode", result)
        self.assertIn("Many subdomain levels", result)
        self.assertIn("Domain was registered about", result)
        self.assertIn("RISK: HIGH", result)


if __name__ == "__main__":
    unittest.main()
