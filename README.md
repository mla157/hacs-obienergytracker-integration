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
- Battery Level
- Online Status
- Connection Strength
- Last Record Received At

## Bruno

Unofficial API for the "heyOBI" backend, as used in this repository. The endpoints are not officially documented.

### Procedure

1. Perform **Login** → sets `token` (JWT) and `userId` (from the JWT payload).
2. Perform **Get bridge info** → sets `bridgeId` and `deviceId` based on the first
   linked sensor.
3. After that, **Get hourly data** and **Get meter data** can be called...

---

*Disclaimer: This integration is not affiliated with or endorsed by OBI. Use at your own risk.*
