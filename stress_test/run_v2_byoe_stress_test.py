"""
v2 "bring your own evidence" stress test — exercises the full scenario
matrix from claude/ANTI_CASSIOPEIA_V2_MASTER_BUILD_PROMPT.md against the
REAL FastAPI app (anticassiopeia.api.server.app) via TestClient: real
/upload, real /verify, real /verify/project, real ml_data.py/
fpga_embedded.py computation against real scratch files, and real live
Nebius calls for the robotics/research_web legs (kept to a small,
deliberate number — see each scenario's own comment for why).

Uses two REAL, openly-licensed (MIT / Apache-2.0) robotics source
documents fetched and verified this session — see
stress_test/PROVENANCE.md's "v2 'bring your own evidence' stress-test
material" section for the full license chain — plus the project's own
pre-existing real/synthetic fixtures (the Espressif SVD excerpt, the
UCI-sourced CSVs, the Vivado report fixtures) for the ml_data/
fpga_embedded legs.

Usage:
    ANTICASSIOPEIA_API_KEY=stress-test-key PYTHONPATH=. python3 stress_test/run_v2_byoe_stress_test.py
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("ANTICASSIOPEIA_API_KEY", "stress-test-key")

from fastapi.testclient import TestClient  # noqa: E402

import anticassiopeia.api.server as server_mod  # noqa: E402
from anticassiopeia.api.server import app  # noqa: E402

API_KEY = os.environ["ANTICASSIOPEIA_API_KEY"]
HEADERS = {"X-API-Key": API_KEY}
client = TestClient(app)

results: list[dict] = []


def reset_rate_limits() -> None:
    """This script is testing FUNCTIONAL correctness of each scenario, not
    re-proving the rate limiter (already covered by its own dedicated
    tests in tests/test_api_server.py, test_upload_endpoint.py,
    test_project_endpoint.py) -- clear every bucket before each call so a
    real, intentional scenario doesn't fail on an incidental 429 from this
    script's own back-to-back calls sharing one API key."""
    server_mod._buckets.clear()
    server_mod._auth_failure_buckets.clear()
    server_mod._upload_buckets.clear()
    server_mod._project_buckets.clear()


def record(scenario: str, description: str, ok: bool, detail: str) -> None:
    results.append({"scenario": scenario, "description": description, "ok": ok, "detail": detail})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {scenario}: {description}")
    if not ok:
        print(f"         {detail}")


def upload(filename: str, content: bytes) -> dict:
    reset_rate_limits()
    resp = client.post("/upload", files={"file": (filename, io.BytesIO(content), "application/octet-stream")}, headers=HEADERS)
    return {"status": resp.status_code, "body": resp.json()}


def verify(text: str, domain: str, context: dict | None = None) -> dict:
    reset_rate_limits()
    resp = client.post("/verify", json={"text": text, "domain": domain, "context": context or {}}, headers=HEADERS)
    return {"status": resp.status_code, "body": resp.json()}


def project(claims: list[dict]) -> dict:
    reset_rate_limits()
    resp = client.post("/verify/project", json={"claims": claims}, headers=HEADERS)
    return {"status": resp.status_code, "body": resp.json()}


def main() -> None:
    print("=" * 80)
    print("v2 BYOE stress test — full scenario matrix, real app, real documents")
    print("=" * 80)

    # --- Scenario 7: no document at all -> falls back to existing fixed-corpus behavior ---
    r = verify("Bar30 survives 500m depth", "robotics")
    record(
        "7", "robotics claim with NO document -> fixed corpus, no regression",
        r["status"] == 200 and r["body"]["state"] == "contradicted",
        json.dumps(r, indent=2),
    )

    # --- Scenario 2: robotics BYOE, real ODrive datasheet, TRUE and FALSE claims (2 live calls) ---
    odrive_bytes = (REPO_ROOT / "evals/fixtures/odrive_v3_6_specifications_excerpt.txt").read_bytes()
    up = upload("odrive_v3_6_specifications_excerpt.txt", odrive_bytes)
    odrive_doc_id = up["body"].get("document_id")
    record("2a", "upload real MIT-licensed ODrive spec excerpt", up["status"] == 200, json.dumps(up, indent=2))

    r = verify(
        "The ODrive v3.6 24V supports a peak current of 120 Amps per motor.",
        "robotics", {"document_id": odrive_doc_id},
    )
    record(
        "2b", "TRUE claim against real ODrive datasheet -> expect confirmed",
        r["status"] == 200 and r["body"]["state"] == "confirmed",
        json.dumps(r, indent=2),
    )

    r = verify(
        "The ODrive v3.6 24V supports a peak current of 300 Amps per motor.",
        "robotics", {"document_id": odrive_doc_id},
    )
    record(
        "2c", "FALSE claim against real ODrive datasheet -> expect contradicted",
        r["status"] == 200 and r["body"]["state"] == "contradicted",
        json.dumps(r, indent=2),
    )

    # --- Scenario 1 & 4: research_web, no document, live search (2 live calls) ---
    r = verify("ODrive is an open-source motor controller project.", "research_web")
    record(
        "1", "research_web, no document, live search about ODrive",
        r["status"] == 200 and r["body"]["state"] in ("confirmed", "undetermined"),
        json.dumps(r, indent=2),
    )

    r = verify(
        "The NASA JPL Open Source Rover project was developed at the California Institute of Technology's Jet Propulsion Laboratory.",
        "research_web",
    )
    record(
        "4", "research_web, no document, live search about NASA JPL rover",
        r["status"] == 200 and r["body"]["state"] in ("confirmed", "undetermined"),
        json.dumps(r, indent=2),
    )

    # --- Scenario 2 (second source): robotics BYOE against the real NASA JPL rover README excerpt ---
    rover_bytes = (REPO_ROOT / "evals/fixtures/nasa_jpl_open_source_rover_readme_excerpt.txt").read_bytes()
    up = upload("nasa_jpl_rover_readme.txt", rover_bytes)
    rover_doc_id = up["body"].get("document_id")
    record("2d", "upload real Apache-2.0 NASA JPL rover README excerpt", up["status"] == 200, json.dumps(up, indent=2))

    r = verify("The NASA JPL Open Source Rover has 10 motors.", "robotics", {"document_id": rover_doc_id})
    record(
        "2e", "TRUE claim against real NASA JPL rover doc -> expect confirmed",
        r["status"] == 200 and r["body"]["state"] == "confirmed",
        json.dumps(r, indent=2),
    )

    r = verify("The NASA JPL Open Source Rover has a top speed of 10 m/s.", "robotics", {"document_id": rover_doc_id})
    record(
        "2f", "FALSE claim against real NASA JPL rover doc (real top speed ~1.6m/s) -> expect contradicted",
        r["status"] == 200 and r["body"]["state"] == "contradicted",
        json.dumps(r, indent=2),
    )

    # --- Scenario 6: real SVD/CSV uploaded (not path-based) -> fpga_embedded/ml_data via upload flow ---
    svd_bytes = (REPO_ROOT / "evals/fixtures/esp32c2_register_map_excerpt.svd").read_bytes()
    up = upload("esp32c2.svd", svd_bytes)
    svd_doc_id = up["body"].get("document_id")
    record("6a", "upload real Apache-2.0 Espressif SVD excerpt", up["status"] == 200, json.dumps(up, indent=2))

    csv_bytes = (REPO_ROOT / "evals/fixtures/sample_measurements.csv").read_bytes()
    up = upload("measurements.csv", csv_bytes)
    csv_doc_id = up["body"].get("document_id")
    record("6b", "upload a real CSV", up["status"] == 200, json.dumps(up, indent=2))

    r = project([
        {
            "text": "RNG's DATA register is at offset 0xB0", "document_id": svd_doc_id,
            "context": {"metric": "register_offset", "peripheral": "RNG", "register": "DATA", "comparator": "==", "expected_value": "0xB0"},
        },
    ])
    claim0 = r["body"]["claims"][0] if r["status"] == 200 else {}
    record(
        "6c", "uploaded SVD sniffed to fpga_embedded, real register check via /verify/project",
        r["status"] == 200 and claim0.get("domain") == "fpga_embedded" and claim0.get("verdict", {}).get("state") == "confirmed",
        json.dumps(r, indent=2),
    )

    # --- Scenario 3 & 5: multi-domain project bundle (robotics BYOE + ml_data + fpga_embedded), one live call ---
    r = project([
        {"text": "The ODrive v3.6 24V supports a peak current of 120 Amps per motor.", "document_id": odrive_doc_id},
        {
            "text": "the mean voltage is 5.0", "document_id": csv_doc_id,
            "context": {"column": "voltage", "stat": "mean", "expected_value": 5.0, "tolerance": 0.05},
        },
        {
            "text": "RNG's DATA register is at offset 0xB0", "document_id": svd_doc_id,
            "context": {"metric": "register_offset", "peripheral": "RNG", "register": "DATA", "comparator": "==", "expected_value": "0xB0"},
        },
    ])
    ok = (
        r["status"] == 200
        and all(c["error"] is None for c in r["body"]["claims"])
        and {c["domain"] for c in r["body"]["claims"]} == {"robotics", "ml_data", "fpga_embedded"}
        and r["body"]["rollup"]["state"] == "confirmed"
    )
    record(
        "3+5", "3-domain bundle (robotics BYOE + ml_data + fpga_embedded) rolled up to confirmed",
        ok, json.dumps(r, indent=2),
    )

    # --- Scenario 10: bundle with nothing routable -> honest undetermined, never fabricated ---
    r = project([{"text": "this references a document that was never uploaded", "document_id": "totally-made-up-id"}])
    claim0 = r["body"]["claims"][0] if r["status"] == 200 else {}
    record(
        "10", "unroutable claim (bad document_id) -> named per-claim error, honest undetermined rollup",
        r["status"] == 200 and claim0.get("error") is not None and r["body"]["rollup"]["state"] == "undetermined",
        json.dumps(r, indent=2),
    )

    # --- Scenario 9: upload too large -> clean 4xx before parsing ---
    reset_rate_limits()
    big = b"x" * (10 * 1024 * 1024 + 1)
    resp = client.post("/upload", files={"file": ("big.txt", io.BytesIO(big), "text/plain")}, headers=HEADERS)
    record(
        "9", "upload over the 10MB cap -> clean 413, not a crash",
        resp.status_code == 413, f"status={resp.status_code} body={resp.text}",
    )

    # --- Scenario 8: malformed upload -> named gap, never a crash ---
    reset_rate_limits()
    resp = client.post("/upload", files={"file": ("broken.pdf", io.BytesIO(b"%PDF-1.4 not a real pdf structure"), "application/pdf")}, headers=HEADERS)
    record(
        "8", "malformed PDF upload -> clean 422 with a named reason, not a crash",
        resp.status_code == 422 and "could not be read as a PDF" in resp.json().get("detail", ""),
        f"status={resp.status_code} body={resp.text}",
    )

    # --- Scenario 11: PDF with no text layer (scanned-image-style) -> named gap, no OCR ---
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    reset_rate_limits()
    resp = client.post("/upload", files={"file": ("scanned.pdf", io.BytesIO(buf.getvalue()), "application/pdf")}, headers=HEADERS)
    record(
        "11", "PDF with no text layer -> clean 422, no extractable text, no OCR attempted",
        resp.status_code == 422 and "no extractable text" in resp.json().get("detail", ""),
        f"status={resp.status_code} body={resp.text}",
    )

    print("=" * 80)
    passed = sum(1 for r in results if r["ok"])
    print(f"{passed}/{len(results)} scenarios passed")
    print("=" * 80)

    report_path = REPO_ROOT / "stress_test" / "results" / "v2_byoe_stress_test_raw.json"
    report_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"Raw results written to {report_path}")

    if passed != len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
