"""BUILDER: an Antigravity Managed Agent turns the design into a real Home Assistant config,
then runs Home Assistant's own checker (`hass --script check_config`) in a Google-hosted
sandbox and fixes errors until it passes.

The sandbox is reused (environment id saved in sandbox_env.txt) so Home Assistant is
installed once, before the demo, not during it:   python validator.py --warm
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pipeline import MODELS, clients

ROOT = Path(__file__).parent
ENV_FILE = ROOT / "sandbox_env.txt"
TOKEN_CAP = 150000

RESULT_INSTRUCTIONS = (
    "When finished, end your reply with ONE fenced ```json block containing exactly these keys: "
    '"first_pass_valid" (bool: did check_config pass before any fixes), "passed" (bool: final result), '
    '"attempts" (int), "errors_fixed" (list of short strings), "check_output_tail" (last 15 lines of the final '
    'check_config output), "configuration_yaml" (string), "automations_yaml" (string).'
)


def _agent(input_text: str, previous_id: str | None = None):
    _, beta = clients()
    env = ENV_FILE.read_text().strip() if ENV_FILE.exists() else "remote"
    kwargs = dict(agent=MODELS["builder_agent"], environment=env, input=input_text,
                  agent_config={"type": "antigravity", "model": MODELS["builder_model"], "max_total_tokens": TOKEN_CAP})
    if previous_id:
        kwargs["previous_interaction_id"] = previous_id
    r = beta.interactions.create(**kwargs)
    if getattr(r, "environment_id", None):
        ENV_FILE.write_text(r.environment_id)
    return r


def _parse(text: str) -> dict:
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text or "", re.S)
    if blocks:
        try:
            return json.loads(blocks[-1])
        except json.JSONDecodeError:
            pass
    return {"passed": False, "first_pass_valid": False, "attempts": 0, "errors_fixed": [],
            "check_output_tail": "Could not parse agent result", "raw": (text or "")[-1500:]}


def warm():
    """Create the sandbox and install Home Assistant once."""
    r = _agent("Set up this sandbox for validating Home Assistant configs: create a Python venv at /workspace/hass-venv, "
               "pip install homeassistant, and confirm `/workspace/hass-venv/bin/hass --version` works. "
               "Then create /workspace/ha with a minimal configuration.yaml (default_config:) and run "
               "`/workspace/hass-venv/bin/hass --script check_config -c /workspace/ha`. Report the version and result.")
    print("Sandbox:", ENV_FILE.read_text().strip() if ENV_FILE.exists() else "(no id returned)")
    print(r.output_text)


def build_and_validate(design_doc: dict) -> dict:
    """Write config from the design, check it, fix until valid."""
    spec = {k: design_doc.get(k) for k in ("hub", "devices", "automations", "offline_behavior", "power_plan")}
    task = (
        "You are the Casa Lista builder. Using the Home Assistant install in /workspace/hass-venv "
        "(if it is missing, create the venv and pip install homeassistant first), write a Home Assistant config "
        "for this offline-first rural smart home into a fresh directory /workspace/ha_job.\n"
        "Rules: everything must work with NO internet (no cloud integrations). Physical Zigbee/LoRa devices are "
        "added later through the UI, so represent each device with YAML-configurable stand-ins "
        "(input_boolean, input_number, template sensors/binary_sensors) named after the device, and write every "
        "automation in automations.yaml against those entities. Include `default_config:` and "
        "`automation: !include automations.yaml`.\n"
        "Then run `/workspace/hass-venv/bin/hass --script check_config -c /workspace/ha_job`. "
        "Record whether this FIRST run passed. If it fails, fix the YAML and re-run until it passes (max 5 attempts).\n"
        f"DESIGN:\n{json.dumps(spec, ensure_ascii=False)}\n\n{RESULT_INSTRUCTIONS}"
    )
    r = _agent(task)
    out = _parse(r.output_text)
    out["environment_id"] = getattr(r, "environment_id", None)
    return out


def check_only(configuration_yaml: str, automations_yaml: str) -> dict:
    """Validate someone else's config WITHOUT fixing it (used to score the baseline fairly)."""
    task = (
        "Write these two files EXACTLY as given (do not edit them) into a fresh directory /workspace/ha_check, then run "
        "`/workspace/hass-venv/bin/hass --script check_config -c /workspace/ha_check` (create the venv and pip install "
        "homeassistant first if it is missing). Do NOT fix anything.\n"
        f"--- configuration.yaml ---\n{configuration_yaml}\n--- automations.yaml ---\n{automations_yaml}\n--- end ---\n"
        + RESULT_INSTRUCTIONS.replace('"first_pass_valid" (bool: did check_config pass before any fixes), ', '"first_pass_valid" (bool), ')
    )
    return _parse(_agent(task).output_text)


if __name__ == "__main__":
    if "--warm" in sys.argv:
        warm()
    else:
        demo = {"hub": "Raspberry Pi 5 + Zigbee dongle", "devices": [{"name": "well pump power monitor", "room": "patio"}],
                "automations": [{"name": "Pump dry-run protection", "trigger": "pump on for 30 min",
                                 "action": "turn pump off and notify"}]}
        print(json.dumps(build_and_validate(demo), indent=2))
