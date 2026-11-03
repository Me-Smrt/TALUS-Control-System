# Camera and audio ownership plan

## Cameras

The Pi owns both planned cameras.

- `aurora`: primary tracking/depth camera. The current OpenCV path handles RGB.
  The Aurora930 Pro depth/IR path will need the vendor SDK and is deliberately
  deferred until the device is physically available.
- `eye`: compact USB camera in the head/eye assembly. It is configured as an
  optional secondary capture source and can be enabled once the actual USB
  device/index is known.

The product documentation for the planned Aurora930 Pro describes RGB, depth,
and IR at 640x400 around 12 fps over USB 2.0 on Linux/ARMv8. A Pi-target example
configuration is included in `config/pi_hardware.example.json`; the default
configuration stays friendlier to ordinary desktop webcams for current R&D.

Only the selected tracking camera currently runs MediaPipe. All enabled cameras
can still provide raw on-demand snapshots through the Pi API. A camera without a
processor returns its raw image as the temporary `processed` fallback.

## Audio

The Pi is planned to own a USB microphone and USB speaker. v0.3 exposes their
configuration/health in RobotState but intentionally does not freeze the audio
transport yet. STT/TTS transport needs to be designed together with the
auxiliary-processor stack so buffering, interruption, wake/voice activity, and
latency are handled coherently instead of bolted on twice.
