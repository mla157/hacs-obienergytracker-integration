# "OBI Energy Tracker" - HACS Integration

This integration allows you to monitor your **OBI Energy Tracker** device directly within Home Assistant. The OBI Energy Tracker is a cost-effective solution for reading smart energy meters, typically accessed via the heyOBI smartphone application.

## Installation

Add this repository via custom repository in HACS: https://www.hacs.xyz/docs/faq/custom_repositories/

## OBI Energy Tracker

<img src="https://bilder.obi.de/d9c6b340-b37f-48fd-92f2-72114bad03ad/prZZK/image.jpeg" width="200" alt="Energy Tracker Device">

The "OBI Energy Tracker" is a low cost device to read out smart energy meters.

## Configuration

Setting up the integration uses standard **OAuth2 with PKCE** via `auth.obi.com`:

1. Go to **Settings** -> **Devices & Services** -> **Add Integration** in Home Assistant.
2. Search for **OBI Energy Tracker**.
3. You will be redirected to the secure OBI login window (`auth.obi.com`).
4. Log in with your OBI account.
5. Home Assistant is granted access without storing your password.

## API Details

The integration retrieves:

- Meter Reading (`Wh`)
- Feed-In Meter Reading (`Wh`)
- Live Power (see below)
- Battery Level (`%`)
- Online Status
- Connection Strength
- Last Record Received At

### Polling & Backend Efficiency
- **Authentication**: Official OAuth2 via `auth.obi.com` with PKCE; tokens are refreshed automatically.
- **Meter reading**: Fetched every 5 minutes with a 15-minute window (`PT15M`), matching the device upload frequency.
- **Device metadata**: Battery, online status, and connection strength are cached and refreshed every 30 minutes.
- **Identification**: Requests identify as `HomeAssistant-ObiEnergyTracker-Integration`.

### Live mode

The heyOBI app shows a real-time power value, and this integration can do the same. It is a **switch**, not an always-on sensor, because live mode works by lowering the sensor's upload interval from 300 to 2 seconds - and that sensor runs on a battery.

Switch `Live mode` on and the `Live Power` sensor updates every two seconds. Switch it off, let it time out, reload the integration or shut Home Assistant down, and the upload interval goes back to 300 seconds.

The timeout defaults to 10 minutes; leaving live mode on permanently will drain the sensor battery.

## Bruno

Unofficial API collection for the heyOBI backend as used during reverse engineering.

---

*Disclaimer: This integration is a community project and is not officially affiliated with or endorsed by OBI. For the official integration, see [OBI-Smart-Technologies/energy-tracker-integration-home-assistant](https://github.com/OBI-Smart-Technologies/energy-tracker-integration-home-assistant).*

> [!NOTE]
> ### Official Integration Available
> OBI has released an official Home Assistant integration:
> **[OBI-Smart-Technologies/energy-tracker-integration-home-assistant](https://github.com/OBI-Smart-Technologies/energy-tracker-integration-home-assistant)**
>
> Both integrations use the domain `obi_energy_tracker`. If you want to use the official integration instead, please uninstall this custom repository first.
