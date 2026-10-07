# Devialet Expert - experimental Home Assistant integration

Native `media_player` for the pre-Core-Infinity Expert UDP protocol, based on
[devimote](https://github.com/gnulabis/devimote). No cloud, GUI or Python package
dependency. Not yet installed in HA.

## HACS installation

Repository: https://github.com/rzomerman/ha-devialet-expert

1. In HACS, open the menu -> Custom repositories.
2. Add the repository URL above, type **Integration**.
3. Find **Devialet Expert**, then download it.
4. Restart Home Assistant.
5. Settings -> Devices & services -> Add integration -> **Devialet Expert**.
6. Enter the amplifier's IPv4 address. Leave read-only enabled initially.

HACS installs the files and manages updates; the Devices & services step creates
the actual media-player entity. This is a custom HACS repository, not a listing
in the default HACS catalog. The repository must be public and contain these
files before it can be installed. No release archive is required: HACS can use
the default branch. Tagged GitHub releases are recommended after HA validation.

## Safety and behavior

- Setup is **read-only by default**, including direct service calls.
- The configured IPv4 address is pinned: another amplifier cannot redirect commands.
- Only CRC-valid status frames update state. Both observed 345-byte frames and
  documented 512-byte frames are accepted. Corrupt/short frames are logged.
- State becomes unavailable after 10 seconds without valid broadcasts.
- Readback is `(raw - 195) / 2` dB, calibrated from the user's physical readings.
- HA's 0..1 slider maps **-97.5..-28 dB**, not the amplifier's full range.
  Physical volume above -28 dB is still reported in `volume_db`; the slider saturates.
- Every command path rejects out-of-range/nonfinite values. Volume steps are 0.5 dB.
- No optimistic state updates. A command waits up to 5 seconds for subsequent
  status matching the requested value, or raises a visible HA service error.
  This is observed-state confirmation, not a protocol acknowledgement.
- Power-on and source changes are refused when reported volume exceeds -28 dB.
  This software cannot limit physical controls, other clients or source gain.
- Writes are experimental. A separately approved live volume test with this client
  confirmed -40.0 -> -40.5 dB from a subsequent CRC-valid status packet.
  Power, mute and source writes have not been physically validated.
  Unit tests of encoding alone are NOT proof of device acceptance.
- No play/pause/seek features: the amplifier is a receiver, not a playback source.
- One entry/listener; do not run another process bound to UDP 45454 alongside it.

## Install

Copy `custom_components/devialet_expert` into HA's `/config/custom_components/`.
Restart HA, then Settings -> Devices & services -> Add integration ->
Devialet Expert. Enter your amplifier's IPv4 address; leave read-only enabled.

The amplifier must broadcast to HA's network. UDP 45454 must reach the HA host
(Docker requires host networking or suitable broadcast handling). If setup retries
with "No Devialet status", check amplifier power, Wi-Fi, VLANs and firewall rules.
An IP ping alone does not verify UDP delivery. The local Windows passive probe
successfully read Devialet-WIFI, Apple TV and -40.0 dB from a 345-byte packet
after an initial timeout. After the approved quieter test it reported -40.5 dB.

Once readback is confirmed, a separate user-approved low-volume test is required
before disabling read-only in integration Options. The local client's approved
volume test passed, but HA-host readback must still be verified. Remote bindings should be
added only after that test; no existing Hub or Astrion mappings are changed here.

## Validate

From this directory, using the existing POC Python environment:

```shell
python -m unittest discover -s tests -v
python -m compileall -q custom_components
python probe.py --host AMPLIFIER_IPV4
```

`probe.py` listens only; it never sends a command. Unit tests use synthetic frames
and fake transports. Full HA runtime validation is still required after installation.

Protocol attribution: Dimitris Lampridis / gnulabis devimote (GPL-3.0-or-later).
This experimental integration is distributed under GPL-3.0-or-later.
See `LICENSE.txt` for the license terms.
