"""Inspect embedded Power BI data and connections without executing M or DAX."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pipeline/powerbi/upgrade"
if not OUT.exists():
    OUT = ROOT


def main():
    model = json.loads((OUT / "Banking_Analytics.SemanticModel/model.bim").read_text())["model"]
    report = json.loads((OUT / "Banking_Analytics.Report/definition.pbir").read_text())
    if report["datasetReference"] != {"byPath": {"path": "../Banking_Analytics.SemanticModel"}}:
        raise ValueError("Unexpected report-to-model connection")
    if model.get("dataSources") or model.get("expressions"):
        raise ValueError("Additional model data sources or shared queries require review")
    tables = []
    forbidden = re.compile(r"(?:Web\.Contents|File\.Contents|Folder\.(?:Files|Contents)|PostgreSQL\.Database|Sql\.Database|Odbc\.|OleDb\.|SharePoint\.|AzureStorage\.)", re.I)
    for table in model["tables"]:
        columns = [column["name"] for column in table["columns"]]
        if any(re.search(r"account|bank|password|token|secret", name, re.I) for name in columns):
            raise ValueError("Identifier or credential column requires review: " + table["name"])
        for partition in table["partitions"]:
            if partition["mode"] != "import" or partition["source"]["type"] != "m":
                raise ValueError("Unexpected partition mode/source")
            query = "\n".join(partition["source"]["expression"])
            if forbidden.search(query):
                raise ValueError("External connection in " + table["name"])
            raw = query.split("Encoded = Text.Combine({", 1)[1].split("}),", 1)[0]
            chunks = re.findall(r'"([A-Za-z0-9+/=]+)"', raw)
            rows = json.loads(zlib.decompress(base64.b64decode("".join(chunks)), -15))
            if any(len(row) != len(columns) for row in rows):
                raise ValueError("Unexpected embedded row width")
            tables.append({"table": table["name"], "rows": len(rows), "columns": columns,
                           "mode": "import", "source": "embedded compressed JSON"})
    result = {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "passed", "report_connection": report["datasetReference"],
        "tables": tables, "external_connections_found": [], "model_data_sources": [],
        "credentials_required_for_initial_refresh": False,
        "native_power_bi_runtime_verified": False,
        "original_workspace_pbix_exported": False,
        "service_export_blocker": "Browser redirects to Fabric signup; organisation reports signup disabled; existing sign-in returns to the same page.",
        "scope": "Reviewed local PBIP source preview; not an export of the original saved workspace report. Name/connection checks are targeted inspection, not a general secret-scanning guarantee.",
    }
    (OUT / "verification/source_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "passed", "tables": len(tables), "external_connections": 0}))


if __name__ == "__main__":
    main()
