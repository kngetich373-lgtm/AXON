class SecurityReviewer:
    """Evidence-first reviewer. It does not execute tools."""
    def review(self, workflow):
        return {"verified": bool(workflow.scope and workflow.evidence), "findings": workflow.findings, "evidence_count": len(workflow.evidence)}
