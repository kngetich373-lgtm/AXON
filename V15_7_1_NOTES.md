# AXON V15.7.1 — Sentinel Security Redesign + Multi-Source URL Intelligence

## Sentinel UI
- URL Threat Analyzer and Authorized Nmap Discovery are now parallel cards with no empty top row.
- Preserves AXON gold/black visual language and existing navigation.
- Nmap output is visible in the same panel after a governed scan.

## URL intelligence
- Added Google Safe Browsing v5 URL threat lookup when configured.
- Added VirusTotal URL report lookup when configured.
- Added urlscan.io historical scan lookup when configured.
- Added PhishTank verified phishing lookup; API key is optional but rate limits apply.
- Added local brand-impersonation, risky-TLD and URL-length indicators.
- Clean results are never labelled SAFE; AXON reports LOW RISK or INCONCLUSIVE and explains that absence of a match is not proof of safety.
- Multiple independent malicious signals promote the verdict to MALICIOUS / PHISHING.

## Nmap
- Added controlled `nmap -Pn -sT --open -T3` execution behind explicit authorization and AXON confirmation.
- User input cannot inject shell operators or arbitrary Nmap flags.
- Optional ports accept numeric lists/ranges only.

## Settings
- Added Sentinel Threat Intelligence settings for Google Safe Browsing, VirusTotal, urlscan.io and PhishTank credentials.
- Credentials use the owner-only integration settings store and remain outside AXON memory.

## Verification
- 43 automated tests pass.
- Sentinel page launches successfully under Xvfb.

## V15.7.1 Voice lifecycle hotfix
- Fixed a Tkinter lifecycle race where delayed Gemini Live output callbacks updated a Voice diagnostic label after the Voice page had been destroyed.
- Pending voice output coalescing jobs are cancelled when navigating away from Voice and during shutdown.
- Late voice callbacks now verify that Voice-page widgets still exist before updating them.
- Added a regression test for callbacks arriving after Voice-page navigation.

## Verification
- 44 automated tests pass under Xvfb.
- 43 non-GUI tests pass in headless mode; the Tk lifecycle regression is skipped when no usable display exists.
- Full AXON desktop startup smoke-tested under Xvfb.
