# Casa Lista

**An AI agent team that watches over the parts of a home nobody can easily check (the cistern, the well pump, the battery bank, the fridge, the AC), then tells the owner what's wrong and what to do, even when they're far away and the internet is down.**

The most important things in a rural or off-grid home are often the hardest to look at. The water level is inside a closed cistern. The pump is out by the well. The battery bank sits in a shed. The fridge holds medicine, and the AC unit keeps an elderly parent safe in the heat. When the owner lives in another city or another country, they find out something failed days later, usually from a phone call.

Casa Lista connects cheap sensors on that infrastructure to a team of Gemini agents. The agents read the sensor streams together with local weather and grid conditions, work out what is actually happening, decide how serious it is, and alert the owner in their own language with a specific next step. Anything that changes the house, like shutting a valve or shedding a load, is proposed by an agent and runs only after the owner approves it.

Open source so anyone can build it themselves, plus a paid install service for everyone who can't. Our first market is rural El Salvador.

Built solo by Marlon Fuentes at the Build with Gemini 4 NYC Hackathon (November 21, 2026). All code in this repo was written during the event.

## What it watches

| Where | Sensor | What the agents catch |
|---|---|---|
| Cistern / water tank | Level sensor | Tank running low before a delivery, a leak draining it overnight |
| Well pump | Power monitor | Pump running dry, which burns it out, or short-cycling |
| Battery bank and solar | Voltage, current, state of charge | Battery won't last the outage, solar underperforming, inverter overheating |
| Fridge / freezer | Power plug + temperature | Fridge off after a power cut, food or medicine warming up |
| AC unit | Power plug + room temperature | AC failed during a heat wave with someone vulnerable at home |
| Weather and surroundings | Local weather station, smoke/heat sensor | Storm or wildfire smoke approaching, plus heat that raises the stakes of an AC failure |
| Grid and internet | Grid voltage, router status | Outage started, how long it has lasted, whether the house can still phone home |

## How it works: a team of agents, each with one job

1. **Monitor (Gemini 4 Neon)** reads the recent sensor history, weather, and any voice note from the family ("the water smells strange"), then writes an incident report: what happened, the likely cause, and the evidence timestamps.
2. **Triage (Gemini Decision 1)** scores the incident in one Decisions API call and picks an action: *ignore, alert the family, send a technician,* or *emergency*. It returns a confidence score, and when confidence is low it escalates one level and never downgrades.
3. **Alert (Gemini 3.8 Flash TTS)** speaks a short alert in Spanish (or the family's language) with the fix, plus written text, so relatives who prefer voice to reading get it too.
4. **Approve before act.** Suggested actions like "shut the main valve" or "shed non-essential loads" wait for the owner's tap.

**Setup, done once per home:**

- **Surveyor (Gemini 4 Hydrogen, agentic video)** watches a phone walkthrough of the property and maps where the tank, pump, battery, panel, router and key appliances are, so every sensor has a place and the Monitor knows the layout.
- **Architect (Gemini 4 Carbon)** designs the sensor and hub setup for that home's power situation: semi-grid, off-grid, or mostly reliable grid. Everything runs locally on a Home Assistant hub, so monitoring continues with no internet.
- **Safety gate (Gemini Decision 1)** labels every install step *DIY* or *licensed electrician*. Anything touching mains wiring goes to a professional.
- **Builder (Antigravity Managed Agent, Gemini 4 Neon)** writes the hub's Home Assistant configuration in a Google-hosted sandbox, runs Home Assistant's own `check_config`, and fixes it until it passes.

## Why rural El Salvador first

- **The grid reaches almost everyone, but it doesn't stay on.** About 98% of Salvadorans have electricity access ([World Bank, 2023](https://statisticsoftheworld.com/country/el-salvador/electricity-access)), so the problem is reliability. Distributors publish scheduled cuts that run [seven to nine hours](https://www.elsalvador.com/?p=1287153) and warn that [water pumps in affected areas can go down too](https://www.elsalvador.com/?p=1295175). A [regional failure on August 1, 2026](https://www.ejecentral.com.mx/tres-paises-de-centroamerica-regitran-apagon) blacked out parts of four Central American countries.
- **The internet mostly isn't there.** Only about [13% of people in rural areas have internet access, vs. 51% in cities](https://diario.elmundo.sv/economia/el-95-de-los-salvadorenos-porta-celulares-pero-solo-36-tiene-internet) (EHPM 2023), and an IDB study puts [rural households with a connection at 4.1%](https://www.iadb.org/es/blog/modernizacion-del-estado/administracion-publica/la-conectividad-digital-social-la-nueva-infraestructura-del-bienestar-en-el-salvador).
- **Many owners are far away.** Families manage these homes from San Salvador, the US, or elsewhere, and need to know about a failure the day it happens.

The same problem exists on off-grid cabins, ranches, farms and island homes anywhere, so nothing in Casa Lista is tied to one country.

## Results

**Verified live on November 21, 2026** (`python smoke_test.py --agent`, real API calls, no mocks):

| Component | Model | Result | Latency |
|---|---|---|---|
| Surveyor | gemini-4-hydrogen | PASS | 3.0 s |
| Architect | gemini-4-carbon | PASS | 2.8 s |
| Baseline | gemini-4-neon | PASS | 2.1 s |
| Safety gate | gemini-decision-1 | PASS: "replace a wall outlet with a smart outlet" scored **0.99** probability of touching mains wiring, so it routes to an electrician | 0.3 s |
| Builder | antigravity-preview-09-2026 (Google-hosted sandbox) | PASS: ran a command in the sandbox and returned `Python 3.12.3` | 11.1 s |

Full evaluation on unseen inputs (agent team vs. single-call baseline) is in progress; results will be added to [`eval/results.md`](eval/results.md).

## Where it still fails

- **Long sandbox jobs drop on weak connections.** Warming the Builder's sandbox (installing Home Assistant, several minutes) failed with `Server disconnected without sending a response` on venue Wi-Fi, while a short sandbox job passed. Fix in progress: run long agent jobs in background mode and poll for the result instead of holding one connection open.
- **The full eval has not been run yet** on filmed walkthroughs, so we make no accuracy claims beyond the checks above.

## What's in this repo

- `pipeline.py`: Surveyor, Architect and Safety gate for setup, plus a single-call baseline for comparison
- `validator.py`: the Antigravity Builder (warm the sandbox, build and validate a config, check-only for the baseline)
- `app.py` and `static/index.html`: a local web app for the setup flow
- `eval.py`: agent team vs. single-call baseline on unseen inputs
- `smoke_test.py`: checks your API key and that every model answers

The monitoring prototype (Monitor, Triage and Alert over simulated sensor feeds) was built in Google AI Studio Build during the event.
<!-- Add the exported AI Studio code to this repo, e.g. in /monitor -->

## Run the setup flow locally

You need Python 3.11+ and a Gemini API key from [Google AI Studio](https://aistudio.google.com/api-keys).

```bash
git clone https://github.com/MarlonCreative/casa-lista.git && cd casa-lista
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then paste your key after GEMINI_API_KEY=
python smoke_test.py          # every model answers once
python validator.py --warm    # installs Home Assistant in the sandbox once
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Safety and privacy

- Casa Lista never tells a family to do mains electrical work themselves. When the safety gate is unsure, it escalates.
- Agents propose actions on the house; a person approves them.
- Sensor data stays on the local hub. No cameras in bedrooms or bathrooms.
- Alerts are guidance, not a substitute for emergency services or a licensed professional on site.

## License

Apache-2.0
