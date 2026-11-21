"""Quick check that your key works and every model answers once.

Run:   python smoke_test.py            (models only, ~20 s)
       python smoke_test.py --agent    (also starts the Antigravity sandbox agent, slower)
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()
if not os.environ.get("GEMINI_API_KEY"):
    print("FAIL: no GEMINI_API_KEY found. Copy .env.example to .env and paste your key after the = sign.")
    sys.exit(1)

from pipeline import MODELS, clients  # noqa: E402

client, beta = clients()
passed = failed = 0


def check(name, fn):
    global passed, failed
    t = time.time()
    try:
        out = fn()
        passed += 1
        print(f"PASS  {name:<38} {time.time() - t:5.1f}s  -> {str(out).strip()[:70]}")
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"FAIL  {name:<38} {time.time() - t:5.1f}s  -> {type(e).__name__}: {str(e)[:200]}")


def ask(model):
    return lambda: client.interactions.create(
        model=model, input="Reply with just the word: ok",
        generation_config={"thinking_level": "low"}).output_text


check(f"Surveyor  {MODELS['surveyor']}", ask(MODELS["surveyor"]))
check(f"Architect {MODELS['architect']}", ask(MODELS["architect"]))
check(f"Baseline  {MODELS['baseline']}", ask(MODELS["baseline"]))
check(f"Safety    {MODELS['safety']}", lambda: beta.decisions.create(
    model=MODELS["safety"],
    input=[{"type": "text", "text": "Install step: replace a wall outlet with a smart outlet."}],
    questions={"mains": {"type": "noul", "instructions": "Does this step touch mains (120/240V) wiring?"}},
).answers["mains"].noul)

if "--agent" in sys.argv:
    import validator
    check(f"Builder   {MODELS['builder_agent']}",
          lambda: validator._agent("Run `python3 --version` and reply with only its output.").output_text)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
