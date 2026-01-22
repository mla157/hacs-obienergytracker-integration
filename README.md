# Obi EnergyTracker Integration

This integration allows you to connect your Obi EnergyTracker solar panel system to Home Assistant.

[![Open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mla157&repository=hacs-obi_energy_tracker&category=energy)
[![Show this integration in your Home Assistant.](https://my.home-assistant.io/badges/integration.svg)](https://my.home-assistant.io/redirect/integration/?domain=obi_energy_tracker)

## Features

- **Authentication**: Secure login with email and password
- **Real-time Energy Data**: Monitor hourly energy production and consumption
- **Multi-day Historical Data**: Fetch energy data for multiple days
- **Negative Energy Tracking**: Track excess energy fed back to the grid

## Installation

1. Copy the `custom_components/obi_energy_tracker` folder into your Home Assistant's `custom_components` directory.
2. Restart Home Assistant.
3. Go to Settings → Devices & Services → Add Integration.
4. Search for "Obi Energy Tracker".
5. Enter your Obi account email, password, and country code

## Configuration

During setup, you'll need:
- **Email**: Your Obi account email address
- **Password**: Your Obi account password
- **Country**: Country code (default: DE for Germany)

## API Details

### Authentication
The integration uses the Obi authentication endpoint:
- Endpoint: `https://www.obi.de/regi/auth/api/public/login`
- Returns a JWT token for subsequent API calls

### Data Endpoints
- **Totals**: Get total energy statistics
- **Hourly Data**: Get hourly energy measurements with customizable duration

### Supported Measures
- `energy`: Energy produced (in Wh)
- `negative_energy`: Energy fed back to grid (in Wh)

## Usage Example

The API client can fetch data for multiple days:

```python
# Get hourly data for the last 7 days
data = await api.async_get_hourly_data(
    start_date=datetime.now(),
    num_days=7
)
```

## File Structure

```
obienergytracker/
├── __init__.py              # Integration setup and entry point
├── api.py                   # API client implementation
├── config_flow.py           # Configuration flow for UI setup
├── const.py                 # Constants and configuration keys
├── manifest.json            # Integration metadata
├── strings.json             # UI translations
└── README.md               # This file
```

## Development

### API Client Methods

- `async_login()`: Authenticate with Obi
- `async_get_totals()`: Fetch total energy statistics
- `async_get_hourly_data(start_date, num_days)`: Fetch hourly data for multiple days

### Configuration Entry

Configuration is stored in Home Assistant's config entry with:
- `email`: User's email
- `password`: User's password
- `country`: Country code

## Security Notes

- Passwords are stored securely by Home Assistant's config entry system
- API tokens are stored in memory and obtained on each login
- Never commit credentials or tokens to version control

## Troubleshooting

### Login Failed
- Verify email and password are correct
- Check internet connection
- Ensure country code is correct (e.g., "DE" for Germany)

### No Data
- Verify the bridge and device IDs are set (requires additional implementation)
- Check the Home Assistant logs for error details

## Future Enhancements

- [ ] Platform implementations (sensor, binary_sensor)
- [ ] Device discovery
- [ ] Bridge and device ID detection
- [ ] Diagnostics support
- [ ] Better error handling and recovery
