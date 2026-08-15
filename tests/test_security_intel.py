import unittest
from unittest.mock import patch

from axon.security_intel import SourceResult, deep_analyze_url, google_safe_browsing, virustotal, phishtank


class Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload


class SecurityIntelTests(unittest.TestCase):
    @patch("axon.security_intel._request")
    def test_google_known_threat_is_malicious(self, req):
        req.return_value = Resp(payload={"threats": [{"url": "https://evil.example/", "threatTypes": ["SOCIAL_ENGINEERING"]}]})
        result = google_safe_browsing("https://evil.example/", "key")
        self.assertEqual(result.verdict, "MALICIOUS")
        self.assertIn("SOCIAL_ENGINEERING", result.detail)

    @patch("axon.security_intel._request")
    def test_virustotal_malicious_engines(self, req):
        req.return_value = Resp(payload={"data": {"attributes": {"last_analysis_stats": {"malicious": 5, "suspicious": 1, "harmless": 60}}}})
        result = virustotal("https://evil.example/", "key")
        self.assertEqual(result.verdict, "MALICIOUS")

    @patch("axon.security_intel._request")
    def test_phishtank_verified_active_is_malicious(self, req):
        req.return_value = Resp(payload={"results": {"in_database": True, "verified": True, "valid": True, "phish_id": 123}})
        result = phishtank("https://evil.example/")
        self.assertEqual(result.verdict, "MALICIOUS")
        self.assertIn("123", result.detail)

    @patch("axon.security_intel.phishtank")
    @patch("axon.security_intel.urlscan")
    @patch("axon.security_intel.virustotal")
    @patch("axon.security_intel.google_safe_browsing")
    @patch("axon.security_intel.analyze_url")
    def test_deep_verdict_never_calls_clean_safe(self, analyze, google, vt, us, pt):
        analyze.return_value = "DOMAIN: example.com\n\nRISK: LOW · SCORE: 0/100\nCONFIDENCE: HIGH\n\nEVIDENCE\n✓ HTTPS was requested"
        google.return_value = SourceResult("Google Safe Browsing", "ONLINE", "NO_MATCH", "No match")
        vt.return_value = SourceResult("VirusTotal", "ONLINE", "NO_DETECTION", "0 malicious")
        us.return_value = SourceResult("urlscan.io", "ONLINE", "NO_REPORT", "No report")
        pt.return_value = SourceResult("PhishTank", "ONLINE", "NO_MATCH", "No match")
        report = deep_analyze_url("https://example.com/", {"google_safe_browsing": "k", "virustotal": "k", "urlscan": "k"})
        self.assertIn("LOW RISK — NO KNOWN THREAT MATCH", report)
        self.assertNotIn("VERDICT: SAFE", report)

    @patch("axon.security_intel.phishtank")
    @patch("axon.security_intel.urlscan")
    @patch("axon.security_intel.virustotal")
    @patch("axon.security_intel.google_safe_browsing")
    def test_deep_verdict_promotes_single_verified_source(self, google, vt, us, pt):
        google.return_value = SourceResult("Google Safe Browsing", "ONLINE", "MALICIOUS", "SOCIAL_ENGINEERING")
        vt.return_value = SourceResult("VirusTotal", "ONLINE", "NO_DETECTION", "0 malicious")
        us.return_value = SourceResult("urlscan.io", "ONLINE", "NO_REPORT", "No report")
        pt.return_value = SourceResult("PhishTank", "ONLINE", "NO_MATCH", "No match")
        report = deep_analyze_url("https://example.com/", {"google_safe_browsing": "k"})
        self.assertIn("VERDICT: MALICIOUS / PHISHING", report)
        self.assertIn("Google Safe Browsing: MALICIOUS", report)


if __name__ == "__main__":
    unittest.main()
