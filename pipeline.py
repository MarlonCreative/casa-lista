"""Casa Lista: walk through your home on video, get an offline-first smart home build plan
for rural, semi-grid and off-grid homes (first market: rural El Salvador).

Four Gemini pieces, four jobs:
  1. SURVEYOR  - Gemini 4 Hydrogen watches the walkthrough video (agentic video understanding)
                 and listens to the narration -> a structured home inventory.
  2. ARCHITECT - Gemini 4 Carbon designs an offline-first system for rural conditions
                 (unreliable or no grid, weak internet, harsh climate): hub, devices, power plan, steps, parts.
  3. SAFETY    - Gemini Decision 1 gates every install step: DIY, licensed electrician, or skip.
  4. BUILDER   - Antigravity Managed Agent writes the Home Assistant config in a Google-hosted
                 sandbox and runs Home Assistant's own config checker until it passes (validator.py).
"""
from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass, field

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODELS = {
    "surveyor": "gemini-4-hydrogen",
    "architect": "gemini-4-carbon",
    "safety": "gemini-decision-1",
    "builder_agent": "antigravity-preview-09-2026",
    "builder_model": "gemini-4-neon",
    "baseline": "gemini-4-neon",
}

_client = _beta = None


def clients():
    global _client, _beta
    if _client is None:
        _client = genai.Client()
        _beta = genai.Client(http_options={"api_version": "v1beta"})
    return _client, _beta


def upload_video(path: str):
    """Upload a walkthrough video and wait until the API has processed it."""
    client, _ = clients()
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    if path.endswith(".mov"):
        mime = "video/quicktime"
    f = client.files.upload(file=path, config={"mime_type": mime})
    for _ in range(90):
        state = str(getattr(f, "state", "ACTIVE"))
        if "PROCESSING" not in state:
            break
        time.sleep(2)
        f = client.files.get(name=f.name)
    if "FAILED" in str(getattr(f, "state", "")):
        raise RuntimeError("Video processing failed")
    return f


def video_part(f) -> dict:
    return {"type": "video", "uri": f.uri, "mime_type": f.mime_type, "processing": "agentic"}


@dataclass
class Job:
    video_path: str
    place: str = "a rural home"
    grid: str = "semi-grid: grid power that cuts out often"  # or off-grid, or mostly reliable grid
    household: str = ""          # optional typed context, e.g. "grandmother lives alone, well pump"
    language: str = "Spanish"    # language for the family-facing summary


@dataclass
class Result:
    inventory: dict = field(default_factory=dict)
    design: dict = field(default_factory=dict)
    safety: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)


# ------------------------------------------------------------------ 1. SURVEYOR (Hydrogen)
INVENTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "narration_transcript": {"type": "string", "description": "What the person says in the video, verbatim, original language."},
        "rooms": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "timestamp": {"type": "string", "description": "mm:ss where this room is best seen"},
            "doors_windows": {"type": "string"},
            "outlets_switches_lights": {"type": "string"},
            "appliances": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"}},
            "required": ["name", "timestamp", "doors_windows", "outlets_switches_lights", "appliances", "notes"]}},
        "electrical": {"type": "string", "description": "Panel/breakers/meter, wiring condition, visible extension cords or hazards."},
        "water": {"type": "string", "description": "Pump, tank, cistern, water heater, if seen or mentioned."},
        "roof_and_sun": {"type": "string", "description": "Roof material and any clue about sun exposure / orientation."},
        "connectivity": {"type": "string", "description": "Router, signal, dead zones, mentioned or seen."},
        "people_and_needs": {"type": "string", "description": "Who lives there and what they say they need (from narration)."},
        "hazards_seen": {"type": "array", "items": {"type": "string"}},
        "uncertain": {"type": "array", "items": {"type": "string"}, "description": "Things you could not see clearly or must ask about."},
    },
    "required": ["narration_transcript", "rooms", "electrical", "water", "roof_and_sun", "connectivity",
                 "people_and_needs", "hazards_seen", "uncertain"],
}


def survey(job: Job, video) -> dict:
    client, _ = clients()
    r = client.interactions.create(
        model=MODELS["surveyor"],
        input=[
            video_part(video),
            ("You are a home surveyor for an offline-first smart home installer working in "
             f"{job.place}. Scrub through this walkthrough video and listen to the narration. "
             f"Power situation reported by the family: {job.grid}. "
             "Record only what you can actually see or hear, with timestamps. If something is unclear, "
             "put it in 'uncertain' instead of guessing. Extra context from the family: "
             f"{job.household or 'none'}"),
        ],
        generation_config={"thinking_level": "medium"},
        response_format=INVENTORY_SCHEMA,
        response_mime_type="application/json",
    )
    return json.loads(r.output_text)


# ------------------------------------------------------------------ 2. ARCHITECT (Carbon)
DESIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary_family": {"type": "string", "description": "3-4 sentence plain-language summary for the family, in the requested language."},
        "summary_installer": {"type": "string", "description": "Technical summary in English."},
        "hub": {"type": "string", "description": "Local hub hardware + Home Assistant, runs with no internet."},
        "devices": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "room": {"type": "string"}, "protocol": {"type": "string"},
            "purpose": {"type": "string"}, "power": {"type": "string"}},
            "required": ["name", "room", "protocol", "purpose", "power"]}},
        "power_plan": {"type": "object", "properties": {
            "critical_loads": {"type": "array", "items": {"type": "string"}},
            "battery_wh": {"type": "number"}, "solar_w": {"type": "number"}, "rationale": {"type": "string"}},
            "required": ["critical_loads", "battery_wh", "solar_w", "rationale"]},
        "offline_behavior": {"type": "array", "items": {"type": "string"}, "description": "What keeps working when power and/or internet is out."},
        "automations": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "trigger": {"type": "string"}, "action": {"type": "string"}},
            "required": ["name", "trigger", "action"]}},
        "install_steps": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "step": {"type": "string"}, "room": {"type": "string"}},
            "required": ["id", "step", "room"]}},
        "bill_of_materials": {"type": "array", "items": {"type": "object", "properties": {
            "item": {"type": "string"}, "qty": {"type": "number"}, "est_usd": {"type": "number"}},
            "required": ["item", "qty", "est_usd"]}},
        "questions_for_family": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary_family", "summary_installer", "hub", "devices", "power_plan", "offline_behavior",
                 "automations", "install_steps", "bill_of_materials", "questions_for_family"],
}

DESIGN_PRINCIPLES = """
Design principles (non-negotiable):
- OFFLINE FIRST: every automation must run locally on the hub with no internet. Cloud is optional extra.
- POWER IS UNRELIABLE OR ABSENT: on a semi-grid, hub, router and critical loads ride on a battery through
  multi-hour outages; off-grid, size solar + battery so they run every day and through cloudy stretches.
- LOW POWER, LOW COST: prefer Zigbee/Thread battery sensors; LoRa for outbuildings, wells, gates far away.
- PLUG-IN BEFORE HARDWIRED: prefer plug-in and battery devices the family can install; anything touching
  mains wiring, breakers or the panel is a separate step for a licensed electrician.
- LOCAL CLIMATE: heat, humidity, cold, dust, insects; specify enclosures where it matters.
- DIGNITY & PRIVACY: no cameras inside bedrooms/bathrooms; data stays in the house.
- Write each install step as ONE physical action so it can be safety-checked on its own.
"""


def design(job: Job, inventory: dict) -> dict:
    client, _ = clients()
    r = client.interactions.create(
        model=MODELS["architect"],
        input=(f"You design open-source, offline-first smart homes for rural, semi-grid and off-grid families.\n"
               f"This home: {job.place}. Power situation: {job.grid}.\n"
               f"{DESIGN_PRINCIPLES}\n"
               f"Family-facing summary language: {job.language}.\n"
               f"Home inventory from the video survey:\n{json.dumps(inventory, ensure_ascii=False)}"),
        generation_config={"thinking_level": "medium"},
        response_format=DESIGN_SCHEMA,
        response_mime_type="application/json",
    )
    return json.loads(r.output_text)


# ------------------------------------------------------------------ 3. SAFETY GATE (Decision 1)
def safety_gate(design_doc: dict) -> list:
    """One Decisions API call scores every install step at once."""
    _, beta = clients()
    steps = design_doc.get("install_steps", [])[:300]
    if not steps:
        return []
    questions = {}
    for s in steps:
        sid = f"s_{s['id']}".replace(" ", "_")
        questions[sid + "_route"] = {
            "type": "choice",
            "instructions": f"Install step: '{s['step']}' (room: {s['room']}). Who should do this step?",
            "criteria": {
                "diy": "Safe for a non-expert homeowner: plug-in devices, battery sensors, app setup, mounting with screws or adhesive, no exposed mains.",
                "electrician": "Touches mains (120/240V) wiring, outlets, switches, breakers, the panel, inverter AC wiring, or the meter. Requires a licensed electrician.",
                "other_pro": "Needs another trade: roof/ladder work at height, plumbing, well or pump internals.",
                "other": "Not a physical step or too unclear to judge.",
            },
        }
        questions[sid + "_risk"] = {
            "type": "score",
            "instructions": f"Rate the personal-safety risk of this step if done wrong: '{s['step']}'.",
            "criteria": ["Negligible risk.", "Minor injury or damaged equipment possible.", "Serious injury, fire or electrocution possible."],
        }
    d = beta.decisions.create(
        model=MODELS["safety"],
        input=[{"type": "text", "text": "Rural home smart-home installation plan. Classify each install step for safety."}],
        questions=questions,
    )
    out = []
    for s in steps:
        sid = f"s_{s['id']}".replace(" ", "_")
        rt, rk = d.answers[sid + "_route"], d.answers[sid + "_risk"]
        who = rt.choice
        # Low confidence on anything that might be electrical -> escalate, never downgrade.
        if rt.confidence < 0.75 and rt.probabilities.get("electrician", 0) > 0.2:
            who = "electrician"
        if rk.score > 0.66 and who == "diy":
            who = "electrician" if rt.probabilities.get("electrician", 0) >= rt.probabilities.get("other_pro", 0) else "other_pro"
        out.append({**s, "who": who, "route_confidence": round(rt.confidence, 2),
                    "p_electrician": round(rt.probabilities.get("electrician", 0), 2), "risk": round(rk.score, 2)})
    return out


def run(job: Job, video=None) -> Result:
    res = Result()
    t = time.time(); video = video or upload_video(job.video_path); res.timings["upload_s"] = round(time.time() - t, 1)
    t = time.time(); res.inventory = survey(job, video); res.timings["surveyor_s"] = round(time.time() - t, 1)
    t = time.time(); res.design = design(job, res.inventory); res.timings["architect_s"] = round(time.time() - t, 1)
    t = time.time(); res.safety = safety_gate(res.design); res.timings["safety_s"] = round(time.time() - t, 2)
    return res


# ------------------------------------------------------------------ BASELINE (single call)
def baseline(job: Job, video) -> dict:
    """What people try first: one call, video in, plan + Home Assistant config out."""
    client, _ = clients()
    schema = {"type": "object", "properties": {
        "plan": {"type": "string"},
        "install_steps": {"type": "array", "items": {"type": "object", "properties": {
            "step": {"type": "string"}, "who": {"type": "string", "enum": ["diy", "electrician", "other_pro"]}},
            "required": ["step", "who"]}},
        "configuration_yaml": {"type": "string"}, "automations_yaml": {"type": "string"}},
        "required": ["plan", "install_steps", "configuration_yaml", "automations_yaml"]}
    t = time.time()
    r = client.interactions.create(
        model=MODELS["baseline"],
        input=[video_part(video), f"Design a smart home for this house ({job.place}; power: {job.grid}). Give install steps (marking who should do each), "
               "and a complete Home Assistant configuration.yaml and automations.yaml."],
        generation_config={"thinking_level": "medium"},
        response_format=schema, response_mime_type="application/json")
    out = json.loads(r.output_text)
    out["latency_s"] = round(time.time() - t, 1)
    return out
