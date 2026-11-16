"""WER vs DW-WER report (PRD §9.5, AC 13). Input: JSONL with {"id","reference","hypothesis","system","audio"}.
Only real transcripts from a real ASR system may be scored; the report states what was measured.
Usage: uv run python scripts/asr_report.py data/asr_eval/pairs.jsonl > ../../docs/ASR_REPORT.md
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import _bootstrap  # noqa: F401

from app.services.voice.dwwer import score

path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()] if path and path.exists() else []
print("# ASR evaluation: WER and DW-WER\n")
if not rows:
    print("**Status: BLOCKED.** No real ASR transcripts have been scored yet. Running this needs (a) recorded Marathi farm"
          " speech with human reference transcripts (for example the IISc Respin agriculture subset) and (b) a configured ASR"
          " system (Bhashini credentials or a local Whisper model). The metric itself is implemented and unit-tested"
          " (apps/api/tests/test_voice_and_rag_units.py).")
    raise SystemExit(0)
agg = defaultdict(lambda: {"n": 0, "err": 0, "ref": 0, "werr": 0.0, "wref": 0.0, "cat": defaultdict(lambda: [0, 0])})
for r in rows:
    s = score(r["reference"], r["hypothesis"])
    a = agg[r.get("system", "unknown")]
    a["n"] += 1
    a["err"] += s.errors
    a["ref"] += s.ref_tokens
    a["werr"] += s.weighted_errors
    a["wref"] += s.weighted_ref
    for c, v in s.by_category.items():
        a["cat"][c][0] += v["errors"]
        a["cat"][c][1] += v["ref"]
print("| System | Utterances | WER | DW-WER |\n|---|---|---|---|")
for sys_, a in agg.items():
    print(f"| {sys_} | {a['n']} | {a['err'] / max(a['ref'], 1):.3f} | {a['werr'] / max(a['wref'], 1):.3f} |")
for sys_, a in agg.items():
    print(f"\n## {sys_}: errors by category\n\n| Category | Errors | Reference tokens |\n|---|---|---|")
    for c, (e, n) in sorted(a["cat"].items()):
        print(f"| {c} | {e} | {n} |")
