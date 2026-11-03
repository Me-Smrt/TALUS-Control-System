# TALUS — Source provenance and third-party notices

TALUS includes original project code/designs as well as interfaces to third-party designs, tools and libraries. Merely linking to or downloading a model does not mean TALUS owns its copyright or can redistribute it.

| External project or asset | Role | Attribution and licensing considerations |
| --- | --- | --- |
| InMoov (Gaël Langevin, https://inmoov.fr/) | Robot-body geometry and reference design | Retain correct attribution; verify the Creative Commons terms applicable to each source; downloaded mesh geometry is excluded here. |
| Sentience Robotics InMoov URDF, and fallback InMoov ROS repositories | URDF, kinematics and mesh reference | Verify per-repository code and geometry licenses and retain any required notices. |
| Will Cogley animatronic head assets | Optional head geometry/mechanical reference | Confirm upstream redistribution terms for 3MF, OBJ and related files; none are included in this source-only distribution. |
| Third-party vendor KiCad symbols, footprints and mechanical assets | PCB libraries and package geometry | Check supplier licensing for each *committed* symbol/footprint. Mechanical meshes are excluded; do not presume vendor license grants unrestricted redistribution. |
| Qwen, Faster-Whisper, Kokoro, Piper, YOLO and other ML components | Local inference providers | Weight files are not distributed. Review each model/software license and required attributions separately; source code imports do not convey third-party rights. |

**Scope:** This is a summary of upstream projects used or referenced by TALUS, not a replacement for file-level license notices. For any third-party content distributed in this repository, preserve the exact creator, source, license, and copyright information that applies to that material. Some upstream assets are downloaded locally rather than redistributed here.

## Distinction between ARC affiliation and authorship

The original TALUS engineering content in this repository is presented as **the repository author's individual technical contribution** to Tennessee Tech's Autonomous Robotics Club (ARC) TALUS project. ARC affiliation does not identify ARC membership as coauthors of this implementation. Source files, documentation, and imported models from the external projects above remain attributable to their respective creators.

The repository's first Git commit captures work already developed locally; it is not a claim about the original development date. See [Authorship and provenance](docs/AUTHORSHIP_AND_PROVENANCE.md).

**Licensing note:** Upstream copyright, licenses, and any applicable project agreements remain in effect. Attribution does not by itself grant permission to redistribute or relicense another creator's work.
