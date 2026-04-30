#!/usr/bin/env python3
import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd, **kwargs):
    return subprocess.run(cmd, text=True, **kwargs)


def count_input_words(path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def generator_running():
    result = run(["pgrep", "-f", "scripts/generate_entries.py"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_excluded_csv(entries_dir, out_path):
    rows = []
    for path in sorted(entries_dir.glob("*.json")):
        data = load_json(path)
        if data.get("include") is False:
            rows.append(
                {
                    "word": data.get("word", ""),
                    "exclude_reason": data.get("exclude_reason", ""),
                    "suitability_score": data.get("suitability_score", ""),
                    "meaning_confidence": data.get("meaning_confidence", ""),
                }
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["word", "exclude_reason", "suitability_score", "meaning_confidence"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_errors_csv(errors_dir, out_path):
    rows = []
    for path in sorted(errors_dir.glob("*.json")):
        data = load_json(path)
        rows.append(
            {
                "word": data.get("word", ""),
                "attempt": data.get("attempt", ""),
                "error_type": data.get("error_type", ""),
                "error": data.get("error", ""),
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["word", "attempt", "error_type", "error"])
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def find_ddk():
    candidates = [
        Path("/Volumes/Additional Tools/Utilities/Dictionary Development Kit"),
        Path("/Volumes/Additional Tools 1/Utilities/Dictionary Development Kit"),
        Path("/Applications/Xcode.app/Contents/Developer/Extras/Dictionary Development Kit"),
    ]
    for path in candidates:
        if (path / "bin" / "build_dict.sh").exists():
            return path
    return None


def build_dictionary(args, log):
    build_cmd = [
        sys.executable,
        "scripts/build_apple_dictionary_source.py",
        "--entries-dir",
        str(args.entries_dir),
        "--output-dir",
        str(args.build_dir),
        "--dict-name",
        "Deep Dict",
        "--package-name",
        "DeepDict",
        "--display-name",
        "Deep Dict",
        "--bundle-id",
        "org.deepdict.dictionary.en-zh",
        "--manufacturer",
        "Deep Dict Project",
        "--xml-name",
        "DeepDict.xml",
        "--clean",
    ]
    log.write("$ " + " ".join(build_cmd) + "\n")
    log.flush()
    run(build_cmd, cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)

    ddk = find_ddk()
    if not ddk:
        raise RuntimeError("Dictionary Development Kit not found")

    make_cmd = ["make", f"DICT_BUILD_TOOL_DIR={ddk}"]
    log.write("$ " + " ".join(map(str, make_cmd)) + "\n")
    log.flush()
    run(make_cmd, cwd=ROOT / args.build_dir, check=True, stdout=log, stderr=subprocess.STDOUT)
    return ddk


def main():
    parser = argparse.ArgumentParser(description="Wait for generation to finish, then build Deep Dict.")
    parser.add_argument("--input", type=Path, default=Path("data/generation-targets/merged-clean/words.csv"))
    parser.add_argument("--entries-dir", type=Path, default=Path("outputs/entries-merged-clean"))
    parser.add_argument("--errors-dir", type=Path, default=Path("outputs/errors-merged-clean"))
    parser.add_argument("--build-dir", type=Path, default=Path("build/deep-dict"))
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--log", type=Path, default=Path("outputs/logs/deep-dict-watch-build.log"))
    args = parser.parse_args()

    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as log:
        expected = count_input_words(ROOT / args.input)
        log.write(f"started_at={datetime.now(timezone.utc).isoformat()}\n")
        log.write(f"expected={expected}\n")
        log.flush()

        while generator_running():
            entry_count = len(list((ROOT / args.entries_dir).glob("*.json")))
            error_count = len(list((ROOT / args.errors_dir).glob("*.json")))
            log.write(f"progress entries={entry_count} errors={error_count}\n")
            log.flush()
            time.sleep(args.poll_seconds)

        # Give the generator a moment to flush summary files.
        time.sleep(5)
        entry_count = len(list((ROOT / args.entries_dir).glob("*.json")))
        error_count = len(list((ROOT / args.errors_dir).glob("*.json")))
        processed = entry_count + error_count
        log.write(f"generation_done entries={entry_count} errors={error_count} processed={processed}\n")

        excluded_count = write_excluded_csv(
            ROOT / args.entries_dir,
            ROOT / "outputs/qa-samples/excluded-merged-clean.csv",
        )
        exported_errors = write_errors_csv(
            ROOT / args.errors_dir,
            ROOT / "outputs/qa-samples/errors-merged-clean.csv",
        )
        log.write(f"exported excluded={excluded_count} errors={exported_errors}\n")
        log.flush()

        summary = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "expected": expected,
            "entry_files": entry_count,
            "error_files": error_count,
            "processed": processed,
            "excluded_csv": "outputs/qa-samples/excluded-merged-clean.csv",
            "errors_csv": "outputs/qa-samples/errors-merged-clean.csv",
            "build_dir": str(args.build_dir),
            "dictionary": None,
            "status": "incomplete",
        }

        if processed < expected:
            log.write("not_building reason=incomplete_generation\n")
        else:
            ddk = build_dictionary(args, log)
            summary["status"] = "built"
            summary["ddk"] = str(ddk)
            summary["dictionary"] = str(args.build_dir / "objects" / "DeepDict.dictionary")

        summary_path = ROOT / "outputs/runs-merged-clean/deep-dict-build-summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log.write(f"summary={summary_path}\n")


if __name__ == "__main__":
    raise SystemExit(main())
