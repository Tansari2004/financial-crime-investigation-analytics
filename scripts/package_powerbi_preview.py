"""Package the inspected source preview; never label it a native-verified report."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pipeline/powerbi/upgrade"


def main():
    tools = SOURCE / "tools"
    tools.mkdir(exist_ok=True)
    for name in ("export_powerbi_snapshot.py", "build_powerbi_model.py", "build_powerbi_report.py",
                 "verify_powerbi_upgrade.py", "audit_powerbi_source.py", "verify_powerquery.cjs"):
        shutil.copyfile(ROOT / "scripts" / name, tools / name)
    files = sorted(p for p in SOURCE.rglob("*") if p.is_file()
                   and p.name != "manifest.json" and "__pycache__" not in p.parts
                   and ".pbi" not in p.parts)
    manifest = {
        "format": "Power BI Project source preview (PBIP/PBIR + TMSL)",
        "source_status": "inspected and offline-verified",
        "native_power_bi_runtime_verified": False, "workspace_report_updated": False,
        "original_workspace_export": False,
        "files": {p.relative_to(SOURCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
    }
    (SOURCE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = ROOT / "pipeline/powerbi/Banking_Analytics_Source_Preview.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for file in files + [SOURCE / "manifest.json"]:
            bundle.write(file, "Banking_Analytics_Source_Preview/" + file.relative_to(SOURCE).as_posix())
    print(json.dumps({"archive": str(archive.relative_to(ROOT)), "bytes": archive.stat().st_size,
                      "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
