# "OBI Energy Tracker" - HACS Integration
This integration allows you to monitor your **OBI Energy Tracker** device directly within Home Assistant. The OBI Energy Tracker is a cost-effective solution for reading smart energy meters, typically accessed via the heyOBI smartphone application.e.

## Installation

Add this repository, via custom repository: https://www.hacs.xyz/docs/faq/custom_repositories/

## OBI Energy Tracker

<img src="https://bilder.obi.de/d9c6b340-b37f-48fd-92f2-72114bad03ad/prZZK/image.jpeg" width="200" alt="Energy Tracker Device">

The "OBI Energy Tracker" is a low cost device to read out smart energy meters. In default you can access the data in the "heyOBI" application on our smartphone.
I extracted the API Calls from the backend of the application, and created this "Home Assistant" Integration.

## Configuration

During setup, you'll need:

- **Email**: Your "OBI" account email address
- **Password**: Your "OBI" account password
- **Country**: Country code (default: DE for Germany)

## API Details

The integration retrieves:

- Meter Reading
- Feed-In Meter Reading
- Live Power (see below)
- Battery Level
- Online Status
- Connection Strength
- Last Record Received At

### Live mode

The heyOBI app shows a real-time power value, and this integration can do the
same. It is a **switch**, not an always-on sensor, because live mode works by
lowering the sensor's upload interval from 300 to 2 seconds - and that sensor
runs on a battery.

Switch `Live mode` on and the `Live Power` sensor updates every two seconds.
Switch it off, let it time out, reload the integration or shut Home Assistant
down, and the upload interval goes back to 300 seconds.

The timeout defaults to 10 minutes and can be changed in the integration's
options; `0` disables it. Leaving live mode on permanently will drain the
sensor battery, so do that deliberately.

## Bruno

Unofficial API for the "heyOBI" backend, as used in this repository. The endpoints are not officially documented.

### Procedure

1. Perform **Login** → sets `token` (JWT) and `userId` (from the JWT payload).
2. Perform **Get bridge info** → sets `bridgeId` and `deviceId` based on the first
   linked sensor.
3. After that, **Get hourly data** and **Get meter data** can be called...

---

*Disclaimer: This integration is not affiliated with or endorsed by OBI. Use at your own risk.*
