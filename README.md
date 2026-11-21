# Casa Lista

**Get an offline-first smart home plan that's safe to build and keeps working when the power and internet go out.**

Casa Lista is an open-source agent team for homes where the grid is unreliable or absent: rural, semi-grid and off-grid, including families who manage a home from abroad. Our first market is rural El Salvador. The family films a phone walkthrough of the house and talks through it in Spanish or English. A few minutes later they get a build plan with battery and solar sizing for their power situation, the automations that matter during a blackout, a parts list with prices, a safety check on every install step, and a Home Assistant configuration that has been run through Home Assistant's own validator.

Open source so anyone can build it themselves, plus a paid install service for everyone who can't.

Built solo by Marlon Fuentes at the Build with Gemini 4 NYC Hackathon (November 21, 2026). All code in this repo was written during the event.

## Why: rural El Salvador as the first market

- **The grid reaches almost everyone, but it doesn't stay on.** About 98% of Salvadorans have electricity access ([World Bank, 2023](https://statisticsoftheworld.com/country/el-salvador/electricity-access)), so the problem is reliability, not access. Distributors publish scheduled cuts that run [seven to nine hours](https://www.elsalvador.com/?p=1287153), warn that [water pumps in the affected areas can go down too](https://www.elsalvador.com/?p=1295175), and a [regional failure on August 1, 2026](https://www.ejecentral.com.mx/tres-paises-de-centroamerica-regitran-apagon) blacked out parts of four Central American countries.
- **The internet mostly isn't there.** Only about [13% of people in rural areas have internet access, vs. 51% in cities](https://diario.elmundo.sv/economia/el-95-de-los-salvadorenos-porta-celulares-pero-solo-36-tiene-internet) (EHPM 2023). An IDB study puts [rural households with an internet connection at 4.1%](https://www.iadb.org/es/blog/modernizacion-del-estado/administracion-publica/la-conectividad-digital-social-la-nueva-infraestructura-del-bienestar-en-el-salvador).

So a smart home there has to run locally, ride through outages on a battery, and never depend on the cloud. The same holds for off-grid cabins, ranches, farms and island homes anywhere, so nothing in Casa Lista is specific to one country: the family picks their power situation (semi-grid, off-grid, or mostly reliable grid) and the agents design for it.

## How it works: four Gemini pieces, four jobs

| Step | Model | Job |
|---|---|---|
| 1. Surveyor | **Gemini 4 Hydrogen**, agentic video | Scrubs the walkthrough video and narration, then writes a structured inventory with timestamps: rooms, outlets, panel, water pump, roof and sun, connectivity, who lives there, hazards, and what it couldn't see clearly. |
| 2. Architect | **Gemini 4 Carbon** | Designs an offline-first system for the home's power situation: a local Home Assistant hub, Zigbee/Thread sensors, LoRa for wells and outbuildings, battery Wh and solar W for the critical loads, blackout behavior, automations, one-action install steps, a parts list in USD, and a summary for the family in their language. |
| 3. Safety gate | **Gemini Decision 1** | One Decisions API call scores every install step: DIY, licensed electrician, other trade, or unclear, plus a risk score. Low confidence near electrical work escalates and never downgrades. |
| 4. Builder | **Antigravity Managed Agent** (Gemini 4 Neon) | Writes the Home Assistant config in a Google-hosted sandbox, runs `hass --script check_config`, and fixes errors until it passes. |

In the web app, every room in the survey has a timestamp. Tap it and the video jumps to the moment the Surveyor saw that room.

## Results

Evaluated on walkthroughs filmed at the venue on the day, never seen before, against a **single Gemini 4 Neon call** baseline (video in, plan plus steps marked by who should do them plus Home Assistant YAML out).

See [`eval/results.md`](eval/results.md) for the full table and per-video results.

<!-- RESULTS_SUMMARY: paste the Summary table from eval/results.md here -->

## Where it still fails

<!-- From eval/results.md "Where it still fails", plus the one fix made after seeing it -->

## Run it

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

Open http://localhost:8000 on your computer, or `http://<your-computer's-IP>:8000` on a phone on the same Wi-Fi to record a walkthrough directly.

To run the evaluation, put walkthrough videos in `eval/videos/` and run `python eval.py`. Check the mains-power labels in `eval/labels.csv`, then run `python eval.py --rescore`.

## Files

- `pipeline.py`: Surveyor, Architect, Safety gate, and the single-call baseline
- `validator.py`: Antigravity builder (warm, build and validate, check-only for the baseline)
- `app.py` and `static/index.html`: the web app
- `eval.py`: Casa Lista vs. baseline on unseen videos
- `smoke_test.py`: checks your key and every model

## Safety notes

Casa Lista never tells a family to do mains electrical work themselves. Anything that touches 120/240 V wiring, outlets, switches, breakers, the panel, inverter AC wiring or the meter is routed to a licensed electrician. When the safety gate is unsure, it escalates. The plan is guidance for a family and an installer, not a substitute for a licensed professional on site.

## License

Apache-2.0
