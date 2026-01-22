# "OBI Energy Tracker" - HACS Integration
This integration allows you to monitor your **OBI Energy Tracker** device directly within Home Assistant. The OBI Energy Tracker is a cost-effective solution for reading smart energy meters, typically accessed via the heyOBI smartphone application.e.

[![Open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mla157&repository=hacs-obi_energy_tracker&category=energy)
[![Show this integration in your Home Assistant.](https://my.home-assistant.io/badges/integration.svg)](https://my.home-assistant.io/redirect/integration/?domain=obi_energy_tracker)

## OBI Energy Tracker

<img src="https://bilder.obi.de/d9c6b340-b37f-48fd-92f2-72114bad03ad/prZZK/image.jpeg" width="200" alt="Energy Tracker Device">

The "OBI Energy Tracker" is a low cost device to read out smart energy meters. In default you can access the data in the "heyOBI" application on our smartphone.
I extracted the API Calls from the backend of the application, and created this "Home Assistant" Integration. 

## Configuration

During setup, you'll need:
- **Email**: Your "OBI" account email address
- **Password**: Your "OBI" account password
- **Country**: Country code (default## API Details & Credits

- **Login Endpoint**: \https://www.obi.de/regi/auth/api/public/login\ (JWT-based authentication)
- **Data Endpoint**: Cloud-based polling for energy statistics and meter dat*Disclaimer: This integration is not affiliated with or endorsed by OBI. Use at your own risk.*cker: debug
  \\\

---

*Disclaimer: This integration is not affiliated with or endorsed by OBI. Use at your own risk.*
n for subsequent API callsce discovery
- [ ] Bridge and device ID detection
- [ ] Diagnostics support
- [ ] Better error handling and recovery
