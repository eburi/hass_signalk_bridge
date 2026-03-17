**SignalK Bridge** connects your vessel's [SignalK](https://signalk.org/) server to Home Assistant via WebSocket.

**Features:**
- Real-time delta stream (no polling)
- Smart path classification into 14 functional domains
- Per-domain publish policies prevent HA flooding (critical for Raspberry Pi)
- 3 profiles: Conservative, Balanced, Realtime
- Device tracker for vessel position
- 10 services for runtime control
- Auto-discovery of new SignalK paths
- SignalK HA add-on auto-detection
