"""Check manually observed clean-Windows acceptance without inventing PASS results."""
import argparse
import json
from pathlib import Path

CLEAN_GATES = (
    "clean_install", "first_run", "plugin_lifecycle", "same_version_repair",
    "upgrade_1_5", "upgrade_api1", "upgrade_api2", "default_uninstall",
    "reinstall_preserve", "confirmed_full_removal", "reinstall_fresh", "no_orphan_workers",
)
HUMAN_GATES = ("installer_ui", "plugin_trust_ui", "cancellation_errors", "dpi_100", "dpi_125", "dpi_150", "security_prompts")


FINAL_PLAN = "v15-final-external-v1"
FINAL_CLEAN_GATES = (
    "clean_install", "first_run", "plugin_lifecycle", "same_version_repair",
    "default_uninstall", "reinstall_preserve", "optional_removal_review", "no_orphan_workers",
)


def required_gates(receipt: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Select an explicit acceptance contract without reinterpreting old receipts.

    Args:
        receipt: Receipt carrying its schema and, for final scope, plan identity.

    Returns:
        Required clean-machine and human gate names.

    Raises:
        ValueError: The receipt names an unknown schema or plan.
    """
    if isinstance(receipt, dict):
        if receipt.get("schema_version") == 1 and not receipt.get("plan_id"):
            return CLEAN_GATES, HUMAN_GATES
        if receipt.get("schema_version") == 2 and receipt.get("plan_id") == FINAL_PLAN:
            return FINAL_CLEAN_GATES, HUMAN_GATES
    raise ValueError("Unsupported receipt")


def receipt_template(plan_id: str | None = None) -> dict:
    """Create pending acceptance fields without asserting any observation.

    Args:
        plan_id: None retains the original Phase 5 contract; FINAL_PLAN selects
            the owner-approved remaining external checks.

    Returns:
        Independent JSON-compatible receipt for a clean-machine reviewer.

    Raises:
        ValueError: An unknown plan is requested.
    """
    identity = {"schema_version": 1} if plan_id is None else {"schema_version": 2, "plan_id": plan_id}
    clean, human = required_gates(identity)
    return {**identity, "status": "PENDING", "environment": {
        "genuinely_clean_windows": False, "windows_build": "", "reviewer": "",
        "source_checkout_absent": False, "developer_tools_not_required": False},
        "artifacts": {"installer_sha256": "", "source_sha256": "", "plugin_sha256": ""},
        "signing_decision": "pending", "signing_reason": "",
        "gates": {key: {"status": "PENDING", "evidence_kind": "", "notes": ""}
                  for key in (*clean, *human)}}


def acceptance_blockers(receipt: dict) -> tuple[str, ...]:
    """Identify missing or contradictory manual release evidence.

    This checks recorded completeness, not the truth of a human attestation.
    Automated and same-host observations cannot satisfy these manual gates.

    Args:
        receipt: Parsed clean-machine acceptance receipt.

    Returns:
        Blocking reasons; empty only for a complete human-recorded PASS receipt.
    """
    try:
        clean, human = required_gates(receipt)
    except ValueError:
        return ("Unsupported receipt",)
    errors = []
    if receipt.get("status") != "PASS":
        errors.append("Overall receipt is not PASS")
    environment = receipt.get("environment", {})
    if not isinstance(environment, dict):
        environment = {}
    for key in ("genuinely_clean_windows", "source_checkout_absent", "developer_tools_not_required"):
        if environment.get(key) is not True:
            errors.append("Unconfirmed environment: " + key)
    for key in ("windows_build", "reviewer"):
        if not isinstance(environment.get(key), str) or not environment[key].strip():
            errors.append("Missing environment: " + key)
    artifacts = receipt.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    for key in ("installer_sha256", "source_sha256", "plugin_sha256"):
        value = artifacts.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            errors.append("Missing exact artifact hash: " + key)
    gates = receipt.get("gates", {})
    if not isinstance(gates, dict):
        gates = {}
    for key in (*clean, *human):
        gate = gates.get(key, {})
        expected = "clean_windows_observed" if key in clean else "human_observed"
        if (not isinstance(gate, dict) or gate.get("status") != "PASS"
                or gate.get("evidence_kind") != expected
                or not isinstance(gate.get("notes"), str) or not gate["notes"].strip()):
            errors.append("Missing observed acceptance: " + key)
    if receipt.get("schema_version") == 2:
        observation = receipt.get("security_observation", {})
        if not isinstance(observation, dict):
            observation = {}
        if observation.get("transfer") != "browser":
            errors.append("Browser/download behavior unobserved; USB is insufficient")
        fields = ("browser_warning", "smartscreen_warning", "defender_alert",
                  "run_anyway_required", "execution_blocked")
        if any(observation.get(key) not in ("Y", "N") for key in fields):
            errors.append("Security observations incomplete")
        if observation.get("defender_alert") == "Y" or observation.get("execution_blocked") == "Y":
            errors.append("Security alert/block requires resolution before release")
    if receipt.get("signing_decision") not in {"unsigned_with_documentation", "sign_before_release"}:
        errors.append("Signing decision pending")
    if not isinstance(receipt.get("signing_reason"), str) or not receipt["signing_reason"].strip():
        errors.append("Signing recommendation has no recorded basis")
    if receipt.get("signing_decision") == "sign_before_release":
        errors.append("Signing and exact signed-artifact revalidation required")
    return tuple(errors)


def main() -> int:
    """Validate a receipt or create a new pending template, without replacing a file.

    Returns:
        Zero for a new pending template or complete receipt; one for missing gates.

    Raises:
        OSError: Input cannot be read or the requested new output already exists.
        ValueError: Input is not valid JSON.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--template", action="store_true")
    args = parser.parse_args()
    if args.template:
        with args.receipt.open("x", encoding="utf-8") as stream:
            json.dump(receipt_template(), stream, indent=2)
        return 0
    blockers = acceptance_blockers(json.loads(args.receipt.read_text(encoding="utf-8-sig")))
    print(json.dumps({"status": "BLOCKED" if blockers else "COMPLETE_RECORDED_ACCEPTANCE", "blockers": blockers}, indent=2))
    return int(bool(blockers))


if __name__ == "__main__":
    raise SystemExit(main())
