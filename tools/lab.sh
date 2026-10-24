#!/usr/bin/env bash
# Run MakerMods Lab (tools/makermodslab) for arm setup: calibrate, teleoperate, check cameras.
# It runs in its own uv-managed environment because it pins its own LeRobot fork, which
# would clash with the `arm` extra in pyproject.toml.
#
#   tools/lab.sh            # UI + API on http://localhost:8000
#
# Lab and the game hub can't share the CAN bus. Stop Lab (Ctrl-C) before starting the hub;
# brain/arm/lab.py makes the hub refuse to connect while a Lab session holds the arms.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null; then
  echo "uv is required: brew install uv, or curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
if [ ! -f tools/makermodslab/pyproject.toml ]; then
  git submodule update --init tools/makermodslab
fi

# gs-usb + pyusb let Lab open the candleLight CAN adapters directly as gs_usb:<serial> (Linux,
# needs tools/udev/99-gs-usb.rules installed).
exec uv tool run --python 3.12 --with gs-usb==0.3.1 --with pyusb --from ./tools/makermodslab makermodslab "$@"
