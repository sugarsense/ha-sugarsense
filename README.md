# Sugar Sense for Home Assistant

Your glucose from [Sugar Sense](https://sugarsense.io) as ordinary Home Assistant sensors. Put it on a
dashboard, color a lamp by your zone, have a speaker say the number, switch a night light on when you
are out of range.

It works with whatever feeds your Sugar Sense account: FreeStyle Libre, Dexcom, Nightscout and the
other sources the app supports. You connect it with a short code, the way you sign a TV in to a
streaming app. No Libre, Dexcom or Sugar Sense password is ever typed into Home Assistant.

> **Home Assistant shows and automates. It never replaces your alerts. Alerts stay on your phone.**
> A lamp or a speaker depends on your network, your Home Assistant and the device itself. Do not rely
> on them to tell you about a low.

## What you need

- The Sugar Sense app on your phone, connected to your sensor ([iPhone and Android](https://sugarsense.io/download)).
- Sugar Sense Premium. Connecting is open to everyone; the readings are shown for Premium accounts.
- Home Assistant 2025.3 or newer.

## Install

### With HACS

1. Open HACS, then the three dots in the top right corner, then **Custom repositories**.
2. Add `https://github.com/sugarsense/ha-sugarsense` with the type **Integration**.
3. Find **Sugar Sense** in HACS, download it, and restart Home Assistant.

[![Open this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=sugarsense&repository=ha-sugarsense&category=integration)

### By hand

Copy the `custom_components/sugarsense` folder into the `custom_components` folder of your Home
Assistant configuration and restart Home Assistant.

## Connect

1. Go to **Settings > Devices & services > Add integration** and pick **Sugar Sense**.

   [![Add the integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=sugarsense)

2. Home Assistant shows a code and a QR code. Scan the QR code with your phone, or open
   `app.sugarsense.io/ha` and type the code.
3. Sign in with the same Google or Apple account you use in the Sugar Sense app and tap **Connect**.
4. Back in Home Assistant, press **Submit**. The window closes by itself once you are connected.

A device called **Sugar Sense (your name)** appears with your sensors. Home Assistant asks for a new reading once
a minute.

To disconnect, delete the integration in Home Assistant. You can also disconnect a Home Assistant you
no longer have from the list on `app.sugarsense.io/ha`.

## Sensors

| Sensor | What it is |
|---|---|
| Glucose | The current reading, in your own unit (mg/dL or mmol/L). The attribute `mgdl` always carries the mg/dL value. |
| Trend | `falling_fast`, `falling`, `steady`, `rising`, `rising_fast`. |
| Change | The change since the reading about five minutes ago, in your unit. |
| Zone | `very_low`, `low`, `in_range`, `high`, `very_high`, by the limits you set in the app. |
| In range | On while the current reading is inside your range. The simplest thing to build an automation on. |
| Last reading | When the reading was taken. |
| Time in range today | Percent of today's readings inside your range. |
| Alerts paused | On while your alerts are snoozed or paused by Quiet hours in the app. |
| Sensor day, Sensor ends | The day of your CGM sensor's life and when it ends, when the app knows it. |
| The four limits | Your very low, low, high and very high limits, for drawing the band on a graph. |

### The 15 minute rule

A reading older than 15 minutes is not current. From that moment **Glucose, Trend, Change, Zone and
In range become `unavailable`**, so a dashboard goes grey and an automation never acts on an old
number. Last reading keeps its time, so you can see how old the last one is. The switch happens at
the exact minute, also when Home Assistant cannot reach the internet.

The numbers are the ones your phone shows: the same zone edges (a reading exactly on your low or high
line is out of range), the same rounding to mmol/L.

## Ready-made automations

Three blueprints ship with the integration. Import one with its button, pick your sensors and your
light or speaker, done.

| Blueprint | What it does | Import |
|---|---|---|
| Light color follows my glucose zone | Red when low, green in range, amber when high. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsugarsense%2Fha-sugarsense%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsugarsense%2Fzone_light.yaml) |
| Say it on a speaker when glucose goes low | One sentence, once per low, with quiet hours. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsugarsense%2Fha-sugarsense%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsugarsense%2Fannounce_low.yaml) |
| Night light when out of range | A dim light at night while you are out of range, off when you are back. | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fsugarsense%2Fha-sugarsense%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsugarsense%2Fnight_light.yaml) |

## A dashboard card

A tile for the number and a graph of the last three hours. The sensor names carry the name of your
Sugar Sense profile (for a profile called Anna K: `sensor.sugar_sense_anna_k_glucose`), so put your own
in place of `your_name`. You find them on the device page, or use **Add to dashboard** there.

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: sensor.sugar_sense_your_name_glucose
    name: Glucose
    state_content:
      - state
      - last_changed
  - type: history-graph
    hours_to_show: 3
    entities:
      - entity: sensor.sugar_sense_your_name_glucose
      - entity: sensor.sugar_sense_your_name_low_limit
      - entity: sensor.sugar_sense_your_name_high_limit
```

## Notices you may see

Home Assistant shows one clear notice under **Settings > Repairs** when there is nothing to show:

- **Sugar Sense Premium is needed.** Start Premium in the app; the readings appear by themselves.
- **No glucose source in Sugar Sense yet.** Connect your sensor in the app.
- **This Sugar Sense account follows someone else.** This version shows the connected account's own
  readings. Connect the account of the person who wears the sensor.

If the link is disconnected from the Sugar Sense side, Home Assistant asks you to connect again with
a new code.

## Privacy

- The integration only reads. It cannot change anything in your Sugar Sense account.
- Home Assistant holds one random session token for your account. It opens the one read this
  integration uses and nothing else, and you can revoke it at any time.
- What Home Assistant sends: its clock offset (to know when your day starts), its version and this
  integration's version, the name you gave your home, and a random-looking name for this
  installation that is derived from, but is not, its Home Assistant id.
- Diagnostics downloads contain no token and no name.

## What it is not

- Not a medical device and not an alert system.
- No insulin, carbohydrate or dosing information, and no predictions.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest tests
```

Issues and questions: [github.com/sugarsense/ha-sugarsense/issues](https://github.com/sugarsense/ha-sugarsense/issues).

## License

MIT. See [LICENSE](LICENSE).
