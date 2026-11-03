# Wye–Delta / Star–Triangle Resistor Network Transformation

Source: Standard three-terminal resistor-network equivalence, with explicit terminal labeling. This project reference is derived from elementary circuit analysis; no external webpage is asserted.

Let the delta triangle have R_AB (A–B), R_BC (B–C), R_CA (C–A). Let the corresponding wye network have R_A, R_B, R_C from terminals A, B, C to its common central node.

Delta to wye: S = R_AB + R_BC + R_CA. R_A = R_AB R_CA / S, R_B = R_AB R_BC / S, R_C = R_BC R_CA / S.

Wye to delta: P = R_A R_B + R_B R_C + R_C R_A. R_AB = P/R_C, R_BC = P/R_A, R_CA = P/R_B.

For a consistency check, equal delta resistances R yield equal wye resistances R/3, and equal wye resistances r yield equal delta resistances 3r.

Do not confuse these with unrelated mathematical transformations. Label three terminals before substituting numerical values. Generalize to complex impedances only for a matching linear network.
