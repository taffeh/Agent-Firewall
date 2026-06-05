"""
Agent Firewall Scanner
Pulls prompts from SecLists LLM_Testing and fires them at Beaker and Bunsen.
Produces a comparison report showing what each agent blocked vs allowed.

Usage:
    python tools/scanner.py                          # run all categories
    python tools/scanner.py --category jailbreak     # specific category
    python tools/scanner.py --limit 20               # cap prompts per file
    python tools/scanner.py --output results.json    # save results
"""
import argparse
import csv
import io
import json
import time
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import requests

PROXY = "https://agent-firewall-proxy-677007322780.europe-west2.run.app"
BEAKER_URL = f"{PROXY}/beaker/prompt"
BUNSEN_URL = f"{PROXY}/bunsen/prompt"

SECLISTS_BASE = "https://raw.githubusercontent.com/danielmiessler/SecLists/master/Ai/LLM_Testing"

PROMPT_SOURCES = {
    "jailbreak_2023": {
        "url": f"{SECLISTS_BASE}/Ethical_and_Safety_Boundaries/jailbreak_prompts_2023_05_07.csv",
        "format": "csv",
        "field": "text",
    },
    "jailbreak_2023_dec": {
        "url": f"{SECLISTS_BASE}/Ethical_and_Safety_Boundaries/jailbreak_prompts_2023_12_25.csv",
        "format": "csv",
        "field": "text",
    },
    "forbidden_questions": {
        "url": f"{SECLISTS_BASE}/Ethical_and_Safety_Boundaries/forbidden_question_set.csv",
        "format": "csv",
        "field": "question",
    },
    "divergence": {
        "url": f"{SECLISTS_BASE}/Divergence_attack/escape_out_of_allignment_training.txt",
        "format": "txt",
    },
    "data_leakage": {
        "url": f"{SECLISTS_BASE}/Data_Leakage/personal_data.txt",
        "format": "txt",
    },
    "bias": {
        "url": f"{SECLISTS_BASE}/Bias_Testing/gender_bias.txt",
        "format": "txt",
    },
}


@dataclass
class Result:
    category: str
    prompt: str
    beaker_response: str
    beaker_error: bool
    bunsen_response: str
    bunsen_blocked: bool
    bunsen_triggered: list
    bunsen_error: bool
    duration_ms: int


def fetch_prompts(source: dict, limit: Optional[int] = None) -> list[str]:
    resp = requests.get(source["url"], timeout=15)
    resp.raise_for_status()

    prompts = []
    if source["format"] == "csv":
        field = source.get("field", "text")
        reader = csv.DictReader(io.StringIO(resp.text))
        for row in reader:
            text = row.get(field, "").strip()
            if text:
                prompts.append(text)
    else:
        for line in resp.text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                prompts.append(line)

    return prompts[:limit] if limit else prompts


def send_prompt(url: str, text: str, timeout: int = 30) -> dict:
    try:
        resp = requests.post(
            url,
            json={"text": text},
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def run_scan(categories: list[str], limit: Optional[int], delay: float) -> list[Result]:
    results = []
    total = 0

    for category in categories:
        source = PROMPT_SOURCES[category]
        print(f"\n[{category}] Fetching prompts from SecLists...")
        try:
            prompts = fetch_prompts(source, limit)
        except Exception as e:
            print(f"  ERROR fetching prompts: {e}")
            continue

        print(f"  {len(prompts)} prompts loaded")

        for i, prompt in enumerate(prompts, 1):
            short = prompt[:60].replace("\n", " ")
            print(f"  [{i}/{len(prompts)}] {short}...")

            start = time.time()

            beaker_data = send_prompt(BEAKER_URL, prompt)
            bunsen_data = send_prompt(BUNSEN_URL, prompt)

            duration = int((time.time() - start) * 1000)

            beaker_error = "error" in beaker_data
            bunsen_error = "error" in bunsen_data

            result = Result(
                category=category,
                prompt=prompt,
                beaker_response=beaker_data.get("text", beaker_data.get("error", "")),
                beaker_error=beaker_error,
                bunsen_response=bunsen_data.get("text", bunsen_data.get("error", "")),
                bunsen_blocked=bunsen_data.get("armor_blocked", False),
                bunsen_triggered=bunsen_data.get("armor_triggered", []),
                bunsen_error=bunsen_error,
                duration_ms=duration,
            )
            results.append(result)
            total += 1

            status = "BLOCKED" if result.bunsen_blocked else "allowed"
            print(f"         Bunsen: {status} | Beaker: {'error' if beaker_error else 'responded'} | {duration}ms")

            if delay > 0:
                time.sleep(delay)

    return results


def print_summary(results: list[Result]):
    if not results:
        print("No results.")
        return

    total = len(results)
    bunsen_blocked = sum(1 for r in results if r.bunsen_blocked)
    beaker_errors = sum(1 for r in results if r.beaker_error)
    bunsen_errors = sum(1 for r in results if r.bunsen_error)

    print("\n" + "=" * 60)
    print("SCAN SUMMARY")
    print("=" * 60)
    print(f"Total prompts tested : {total}")
    print(f"Bunsen blocked       : {bunsen_blocked} ({bunsen_blocked/total*100:.1f}%)")
    print(f"Bunsen allowed       : {total - bunsen_blocked - bunsen_errors} ({(total-bunsen_blocked-bunsen_errors)/total*100:.1f}%)")
    print(f"Beaker errors        : {beaker_errors}")
    print(f"Bunsen errors        : {bunsen_errors}")

    # Per category breakdown
    categories = sorted(set(r.category for r in results))
    if len(categories) > 1:
        print("\nBy category:")
        for cat in categories:
            cat_results = [r for r in results if r.category == cat]
            blocked = sum(1 for r in cat_results if r.bunsen_blocked)
            print(f"  {cat:<25} {blocked}/{len(cat_results)} blocked by Bunsen")

    # Triggered filters
    all_triggered = []
    for r in results:
        all_triggered.extend(r.bunsen_triggered)
    if all_triggered:
        print("\nFilters triggered:")
        for f in sorted(set(all_triggered)):
            count = all_triggered.count(f)
            print(f"  {f}: {count}x")

    print("=" * 60)


def save_results(results: list[Result], output_path: str):
    data = {
        "scan_time": datetime.utcnow().isoformat(),
        "total": len(results),
        "results": [asdict(r) for r in results],
    }
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nResults saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Agent Firewall Scanner")
    parser.add_argument(
        "--category",
        choices=list(PROMPT_SOURCES.keys()),
        help="Run a specific category only (default: all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max prompts per category (default: 10)",
    )
    parser.add_argument(
        "--output",
        default=f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        help="Output file for results (default: scan_<timestamp>.json)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds between prompts to avoid rate limiting (default: 1.0)",
    )
    args = parser.parse_args()

    categories = [args.category] if args.category else list(PROMPT_SOURCES.keys())

    print(f"Agent Firewall Scanner")
    print(f"Categories : {', '.join(categories)}")
    print(f"Limit      : {args.limit} per category")
    print(f"Proxy      : {PROXY}")

    results = run_scan(categories, args.limit, args.delay)
    print_summary(results)
    save_results(results, args.output)


if __name__ == "__main__":
    main()
