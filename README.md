# TALUS — Distributed Humanoid Robotics Platform

Welcome to my contribution to **TALUS**, a project of Tennessee Tech's [Autonomous Robotics Club (ARC)](https://www.instagram.com/tntecharc/)! This repository showcases my independently developed hardware, software, and simulation work for the project.

In the interest of transparency, much of the documentation was written with the help of AI (credit where it's due! 🤣), but the engineering work represented here is my own.

I hope you find the project interesting as you explore the repository! I also plan to add photos of TALUS and demonstrations of the simulations as the project progresses.

---

TALUS is an experimental humanoid/automaton platform for on-campus information assistance, conversational interaction, deterministic visual perception, and safely mediated robot behaviors. The intended primary use is answering questions about **Tennessee Tech** and interacting with people on campus.

> **R&D / safety status:** This repository includes hardware designs, draft control firmware, AI software, computer vision, and Blender simulations. Passing source-level tests does **not** establish that actuator power, emergency-stop paths, collision prevention, or complete motion are validated on physical hardware. Physical motion must remain disabled until formal bench verification.

## Authorship and project background

TALUS is part of the work of Tennessee Tech's Autonomous Robotics Club (ARC). **This repository showcases my individual engineering contribution to TALUS**, including the electronics and PCB designs, distributed control architecture, original firmware, AI/voice integration, computer vision and kinematics software, simulation tools, and operator dashboard. I developed and integrated these TALUS-specific components independently.

The project also builds on excellent work from the wider robotics and open-source communities. InMoov, the Will Cogley head, external CAD and URDF references, machine-learning models, and software dependencies remain the work of their respective creators. See [Third-party acknowledgments](THIRD_PARTY_NOTICES.md) for details.

**Development began before this Git repository.** The first commit is a snapshot of work already developed and tested locally, rather than the project's starting date. [Authorship and development history](AUTHORSHIP.md) provides context for earlier milestones.

**Author:** Tyler Krumm · [GitHub profile](https://github.com/Me-Smrt)

## How the system is divided

| Directory | Responsibility |
| --- | --- |
| [`Design/`](Design/) | KiCad CCB and RCB design files, project-local symbols/footprints and text-based manufacturing documentation (3D vendor assets are not committed) |
| [`Model/`](Model/) | InMoov and optional Will Cogley head Blender builder scripts; generated models are local-only |
| [`Software/Raspberry PI 5/`](Software/Raspberry%20PI%205/) | Pi 5 hardware authority: Supervisor UART, GPIO heartbeat, SocketCAN and RCB sessions |
| [`Software/Central Control Module/`](Software/Central%20Control%20Module/) | CCB safety-supervisor firmware draft |
| [`Software/Remote Control Module/`](Software/Remote%20Control%20Module/) | RCB firmware draft: CAN, local PWM/servo safety, UID/role pairing |
| [`Software/CV R&D/`](Software/CV%20R%26D/) | Pi-side MediaPipe perception, IK/retargeting, state API, Blender simulation |
| [`Software/Auxiliary Processor R&D/`](Software/Auxiliary%20Processor%20R%26D/) | Local Qwen, STT/TTS, engagement, YOLO tracking, world state, campus knowledge |
| [`Software/Dashboard/`](Software/Dashboard/) | Flask operator interface and authenticated read-only status/diagnostics |

## Authority boundaries

```text
Pi cameras / MediaPipe / deterministic IK
              |                          AUX computer: Qwen / Whisper / Kokoro / YOLO
              |                                |
              +-- Pi control & state API <----+ (semantic behavior requests only)
                             |
                    CCB safety supervisor
                             |
                   CAN channels -> RCBs -> actuators

Flask dashboard -> authenticated status / camera / diagnostics APIs
```

The AUX AI **cannot** directly write raw servo positions, CAN/PWM commands, arm state, power enables, or emergency-stop controls. The Pi behavior layer is responsible for deterministic arbitration and safety checks; independent CCB/RCB safeguards remain mandatory.

## Current development capabilities

- Local LLM reasoning, offline speech recognition and voice-selectable TTS; spoken readiness cue before accepting conversation input.
- Experimental full-duplex acoustic echo cancellation and barge-in; **live hardware validation remains outstanding**.
- Pi-owned camera stream, MediaPipe pose/facial expression data, and Blender retargeting.
- Low-rate YOLO-based anonymous person/object tracking with timestamped world-state snapshots; background perception is deterministic rather than Qwen-driven.
- Local Tennessee Tech knowledge retrieval through SQLite FTS5; source documents can be rebuilt into a runtime database.
- Experimental Blender gestures, simplified arm-collision screening, and IK stability limits; **not physical safety certification**.
- CCB/RCB and Pi control firmware drafts with deliberate hardware-actuation development locks.

See [Project Status](PROJECT_STATUS.md) for what remains to be tested.

## Getting started

1. Choose a subsystem from the table above and follow its component README for installation and configuration. Components may require separate Python environments or PlatformIO toolchains.
2. Obtain the AI model weights, vendor CAD references, and Blender head assets listed in the relevant component README. These are **not** included in this source-only repository.
3. For AUX console testing, see [`Software/Auxiliary Processor R&D/README.md`](Software/Auxiliary%20Processor%20R%26D/README.md); for Pi CV and Blender simulation, see [`Software/CV R&D/README.md`](Software/CV%20R%26D/README.md).

### 3D Component Models

This repository includes the editable KiCad hardware designs, symbols, and footprints, but excludes externally sourced STEP models to keep the repository lightweight. These models are used for 3D visualization and mechanical reference and can be downloaded from their respective manufacturers. Their absence does not affect the electrical schematic or PCB layout.

### Licensing at a glance

I'm sharing my original TALUS software and Blender builder/helper scripts under the **Mozilla Public License 2.0 (MPL-2.0)**. You're welcome to explore, use, and build on that work under the terms of the license. Its file-level sharing requirements help improvements to the covered code remain available to others.

My original Central Control Module and Remote Control Module KiCad designs are shared under the **CERN Open Hardware Licence v2 — Weakly Reciprocal (CERN-OHL-W-2.0)**. Third-party footprints, symbols, component models, and other upstream material keep their own terms. See [Licensing by component](LICENSE_SCOPE.md), [Hardware design licensing](Design/LICENSING.md), and [Third-party acknowledgments](THIRD_PARTY_NOTICES.md).

## Source-only distribution and authorship

Blender project files (`.blend`), AI model weights, CAD input meshes, vendor STEP files, local runtime databases and generated packages are intentionally excluded. Builder scripts and component READMEs describe how to obtain or generate locally required assets; the Will Cogley head builder may require manually supplied reference files not available from automated downloads.

See [Third-party acknowledgments](THIRD_PARTY_NOTICES.md) for the external projects and libraries that informed or support TALUS. Each component retains the credit and license appropriate to its source.
