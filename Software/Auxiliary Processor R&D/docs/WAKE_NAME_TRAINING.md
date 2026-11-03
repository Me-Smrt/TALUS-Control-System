# TALUS wake-name alias training

TALUS uses two complementary mechanisms for wake-name reliability:

1. Faster-Whisper receives a small hotword hint (`TALUS`, `Talus`, `Talos`) during normal STT.
2. `EngagementManager` recognizes a deterministic, auditable list of common STT aliases only in direct-address positions. It does **not** rewrite the transcript globally.

`Hey Robot` remains a fallback wake phrase.

## Real-voice training

Twenty varied real recordings are the recommended first run:

```powershell
python tools\wake_alias_trainer.py --record --trials 20
```

The trainer intentionally disables Whisper hotword bias so it can observe the model's raw mistakes. It writes:

- `runtime/telemetry/wake_alias_training_latest.json`
- `runtime/telemetry/wake_alias_training_latest.md`

The report contains the transcription frequency distribution (mode), mean spelling similarity, mean edit distance, mean language confidence, mean transcription latency, and suggested new aliases. It never edits the live alias configuration automatically.

To analyze recordings made elsewhere:

```powershell
python tools\wake_alias_trainer.py --audio-dir .\wake_samples --trials 20
```

To gather a larger validation set later:

```powershell
python tools\wake_alias_trainer.py --record --trials 100 --keep-audio
```

A categorical transcription such as `Talus`/`Talos` has no meaningful arithmetic mean. The useful statistics are the mode/frequency distribution plus numerical averages for distance, similarity, confidence, and latency.

## Named microphone/environment profiles

Save each calibration run under a descriptive profile name so development microphones do not overwrite the final robot baseline:

```powershell
python tools\wake_alias_trainer.py --record --trials 20 --profile laptop_mic --keep-audio
python tools\wake_alias_trainer.py --record --trials 20 --profile usb_mic_bench --keep-audio
python tools\wake_alias_trainer.py --record --trials 20 --profile usb_mic_robot_installed --keep-audio
```

Each run still updates `runtime/telemetry/wake_alias_training_latest.{json,md}` for convenience, and also writes a persistent profile report under:

```text
runtime/wake_alias_training/profiles/<profile>/report.json
runtime/wake_alias_training/profiles/<profile>/report.md
```

If `--keep-audio` is supplied, the recordings are kept under that profile's `audio/` directory.

Compare profiles after the final microphone is installed:

```powershell
python tools\wake_alias_trainer.py --compare-profiles laptop_mic usb_mic_bench usb_mic_robot_installed --primary-profile usb_mic_robot_installed
```

This writes `runtime/wake_alias_training/comparison_latest.{json,md}`. The primary/final-hardware profile is double-weighted in the recommended alias union so a laptop microphone cannot dominate the deployed robot's behavior.

The trainer never edits the live wake alias configuration automatically. Review the suggested union and add only repeatable, sufficiently similar variants; rare one-off errors should not become wake words.
