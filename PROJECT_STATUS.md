# TALUS — Project Status

TALUS is an ongoing robotics research and development project. This page is a **living overview of the work represented in this repository**, how the major subsystems fit together, and the areas that require further validation. It is not a release announcement, an exhaustive task list, or a certification of the completed robot.

The repository contains a mix of editable hardware designs, application and firmware code, experimental integrations, and Blender simulation tooling. **A feature appearing in source code does not necessarily mean it has been validated on the physical robot.** For precise changes and historical milestones, see the Git commit history and component-specific documentation.

## Subsystems and development focus

| Area | What the repository contains | Engineering and validation focus |
| --- | --- | --- |
| **Central and remote control boards (CCB / RCB)** | Editable KiCad schematics and PCB layouts, control/safety circuitry, project-local symbols and footprints. | Manufacturing and assembly checks; rail and current measurements; hardware watchdogs, emergency-stop behavior, servo authorization, CAN communication, and hot-swap response. |
| **Raspberry Pi control and firmware** | The hardware-facing control architecture, supervisor and CAN communications, RCB identity/pairing logic, and deterministic behavior interfaces. | Integration with assembled CCB/RCB hardware; fault handling; timing, telemetry, and actuator commissioning. |
| **Auxiliary AI and conversation** | Local language-model integration, speech recognition and synthesis, engagement handling, spoken startup readiness, and experimental echo cancellation and barge-in. | Real-microphone behavior, reliable audio gating, latency, and operation across supported machines and modes. |
| **Visual awareness and world state** | Object/person perception, anonymous tracking, timestamped observations, and selective use of scene context in language-model requests. | Multi-person continuity, occlusion, stale observations, grounding accuracy, and efficient continuous inference. |
| **Tennessee Tech knowledge** | Tools for collecting, reviewing, indexing, and querying campus information, plus an optional separate path for technical references. | Official-source coverage, accuracy, freshness, reproducible database builds, and reliable answers to real campus questions. |
| **Computer vision and kinematics** | MediaPipe-based body/face perception, pose retargeting, IK and stability checks, and a Blender-facing simulation interface. | Camera calibration, jitter reduction, joint-space correctness, pose predictability, and collision checks against accurate robot geometry. |
| **Blender models and behaviors** | Scripts for generating the InMoov body, integrating an optional expressive head, driving facial controls, and exercising simulated gestures. | Mechanical alignment, facial-linkage behavior, safe motion paths, and correspondence between simulated and physical joint limits. |
| **Operator dashboard** | Flask-based interfaces for operation, diagnostics, and status visibility across robot services. | Live-service integration, authentication, failure handling, useful telemetry, and operator workflows. |

These descriptions identify the **scope of development**, not a claim that every listed integration works end-to-end. Refer to each subsystem's README and tests for its actual setup requirements and verification evidence.

## Safety and system boundaries

TALUS is designed around a separation of responsibilities:

- The **auxiliary language model** may request high-level semantic behaviors, but must not directly energize actuators or issue raw servo/CAN/PWM commands.
- The **Raspberry Pi controller** owns deterministic command arbitration, motion constraints, and the interface to the hardware control system.
- The **CCB and RCB hardware safeguards** provide independent power, authorization, and watchdog protections. Software checks do not replace them.

Collision screening, IK stability gates, and Blender simulations help evaluate motion, but **they are not proof of physical collision safety**. Full-body geometry, mechanical limits, emergency-stop behavior, watchdog responses, and power controls must be verified before unrestricted physical actuation.

## Ongoing development and verification

The project continues to evolve across several connected workstreams:

- **Reproducible setup:** keeping a source-only repository usable through documented dependencies, model builders, configuration examples, and knowledge-base generation scripts.
- **Perception and interaction:** improving tracking, grounding, spoken interaction, and useful campus-information coverage without unnecessary inference overhead.
- **Motion and simulation:** refining camera-to-robot retargeting, detailed collision prevention, expressive head integration, and gesture behavior in Blender.
- **Hardware integration:** validating the Pi–CCB–RCB control chain, communications, power supervision, watchdogs, and actuator safety through staged bench tests.
- **Diagnostics:** making robot state, failures, and performance observable through logs, APIs, and the operator dashboard.

A subsystem should be described as **hardware-validated** only when corresponding physical testing has actually been completed. Individual test results and known issues are best recorded alongside their component code or in version-control issues, rather than as an ever-growing dated checklist here.

## Component documentation

- [Software overview](../Software/README.md)
- [AUX setup and architecture](../Software/Auxiliary%20Processor%20R%26D/README.md)
- [Computer vision, IK, and Blender simulation](../Software/CV%20R%26D/README.md)
- [Raspberry Pi control](../Software/Raspberry%20PI%205/README.md)
- [Dashboard](../Software/Dashboard/README.md)
- [Hardware design licensing](../Design/LICENSING.md)

For the project's original engineering contributions and development predating this Git repository, see [Authorship](../AUTHORSHIP.md).
