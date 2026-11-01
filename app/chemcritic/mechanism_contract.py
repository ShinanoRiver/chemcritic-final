"""Engineering contracts for A3/A4 proposals; never a chemical approval.

Referenced IDs only establish traceability, not that a paper supports a mechanism.
The entry gate consumes an already-reviewed upstream placement; it does not create
or unlock one, and no proposed experiment is executed by this module.
"""

import math


def entry_gate(report):
    reasons = []
    if report.get("product_evidence", {}).get("state") != "human_review_recorded":
        reasons.append("product_evidence_requires_human_review")
    if report.get("placement_allowed") is not True:
        reasons.append("placement_not_authorized")
    placement = report.get("placement") or {}
    if placement.get("state") != "below_reviewed_reference":
        reasons.append("no_reviewed_below_reference_trigger")
    return {"state": "blocked" if reasons else "eligible_for_draft_only", "reasons": reasons,
            "chemical_approval_granted": False, "experiments_executed": False}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be nonempty text")


def validate_proposals(mechanisms, known_records):
    """Validate traceability/shape only, returning drafts requiring A's review."""
    if not isinstance(mechanisms, list) or not 1 <= len(mechanisms) <= 6:
        raise ValueError("Expected 1 to 6 mechanism drafts")
    identifiers = set()
    for item in mechanisms:
        _text(item.get("id"), "mechanism.id")
        if item["id"] in identifiers:
            raise ValueError("Duplicate mechanism ID")
        identifiers.add(item["id"])
        _text(item.get("hypothesis"), "hypothesis")
        refs = item.get("supporting_refs")
        if not isinstance(refs, list):
            raise ValueError("supporting_refs must be explicit")
        for ref in refs + item.get("counter_refs", []):
            rid = ref.get("record_id")
            source = known_records.get(rid)
            if source is None:
                raise ValueError("Unknown referenced record: " + str(rid))
            if not source.get("doi") or not source.get("locator"):
                raise ValueError("Reference lacks DOI/locator: " + str(rid))
            _text(ref.get("claim_to_check"), "claim_to_check")
        if item.get("confidence") not in {"supported_claim_pending_review", "speculative"}:
            raise ValueError("Draft confidence must not imply scientific approval")
        if not refs and item["confidence"] != "speculative":
            raise ValueError("No supporting reference: must remain speculative")
        if not refs and item.get("prior_rank", 99) <= 2:
            raise ValueError("Speculative draft cannot occupy first two ranks")
        test = item.get("discriminating_test") or {}
        for key in ("action", "observable", "support_if", "exclude_if", "stop_rule"):
            _text(test.get(key), "discriminating_test." + key)
        variables = test.get("changed_dimensions")
        if not isinstance(variables, list) or not variables:
            raise ValueError("Changed dimensions must be explicit")
        if len(variables) > 1 and test.get("system_replacement") is not True:
            raise ValueError("Multiple changed dimensions require explicit system replacement")
    return {"state": "draft_contract_valid", "requires_domain_review": True,
            "mechanism_ids": sorted(identifiers), "source_support_independently_verified": False}


def validate_decision_tree(nodes, mechanism_ids):
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("Decision tree must contain nodes")
    ids = [n.get("id") for n in nodes]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Decision node IDs must be unique")
    links = {}
    for node in nodes:
        cost = node.get("cost_days")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost <= 0:
            raise ValueError("Positive finite cost required")
        targets = node.get("distinguishes")
        if not isinstance(targets, list) or not targets or not set(targets) <= set(mechanism_ids):
            raise ValueError("Node must distinguish known mechanisms")
        _text(node.get("stop_rule"), "node.stop_rule")
        branches = node.get("branches")
        if not isinstance(branches, list) or not branches:
            raise ValueError("Explicit observable branches required")
        links[node["id"]] = []
        for branch in branches:
            _text(branch.get("observation"), "branch.observation")
            target = branch.get("next")
            if target != "STOP":
                if target not in ids:
                    raise ValueError("Decision branch points to missing node")
                links[node["id"]].append(target)
    visiting, done = set(), set()
    def walk(node):
        if node in visiting:
            raise ValueError("Decision tree contains a cycle")
        if node in done:
            return
        visiting.add(node)
        for target in links[node]:
            walk(target)
        visiting.remove(node)
        done.add(node)
    walk(ids[0])
    if len(done) != len(ids):
        raise ValueError("Unreachable decision node")
    return {"state": "draft_tree_contract_valid", "requires_domain_review": True,
            "experiments_executed": False, "costs_are_declared_estimates": True}
