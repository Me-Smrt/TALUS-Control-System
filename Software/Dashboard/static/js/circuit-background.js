(() => {
    "use strict";

    const host = document.getElementById("circuit-background");
    if (!host) return;

    const NS = "http://www.w3.org/2000/svg";
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    const config = {
        horizontalSpacing: 96,
        verticalSpacing: 92,
        pathCountMin: 30,
        pathCountMax: 48,

        // The SVG is in document space. Moving it down by part of scrollY
        // cancels normal page movement and produces slower apparent scrolling.
        // This is intentionally applied directly with no easing so the circuit
        // layer remains visually locked to the page instead of trailing it.
        parallaxFactor: 0.58,

        // Start points are stratified across the page rather than sampled purely
        // independently. This keeps randomness while strongly reducing clumps.
        edgeStartFraction: 0.24,
        startJitterMin: 0.18,
        startJitterMax: 0.82,

        // Irregular background activity.
        pulseIntervalMin: 520,
        pulseIntervalMax: 1650,
        pulseBurstMin: 1,
        pulseBurstMax: 4,
        pulseBurstExtraChance: 0.56,
        pulseStaggerMax: 620,
        activityRadiusMin: 95,
        activityRadiusMax: 145,

        // Cursor interaction. Deliberately dimmer than random activity.
        cursorRadius: 165,
        cursorTraceLimit: 5,
        sampleSpacing: 32,

        // Long pages receive a modest vertical-routing bias.
        maxVerticalBias: 0.13
    };

    let svg;
    let defs;
    let traceLayer;
    let hoverLayer;
    let pulseLayer;
    let cursorMaskCircle;

    let paths = [];
    let activePulses = [];
    let pulseTimer = null;
    let pulseAnimationFrame = null;
    let resizeTimer = null;

    let pointerTicking = false;
    let lastPointerEvent = null;

    let documentHeight = 0;
    let viewportWidth = 0;
    let visualRandom = Math.random;

    // Fresh per page load. Rebuilds during the same load keep the same layout,
    // but an actual refresh generates a new circuit field.
    const pageSeed = (() => {
        if (window.crypto?.getRandomValues) {
            return window.crypto.getRandomValues(new Uint32Array(1))[0] >>> 0;
        }
        return (Date.now() ^ Math.floor(Math.random() * 0xffffffff)) >>> 0;
    })();

    function mulberry32(seed) {
        return function () {
            let t = seed += 0x6D2B79F5;
            t = Math.imul(t ^ (t >>> 15), t | 1);
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    function resetVisualRandom() {
        visualRandom = mulberry32(pageSeed);
    }

    function randomBetween(min, max, rng = visualRandom) {
        return min + rng() * (max - min);
    }

    function randomInt(min, max, rng = visualRandom) {
        return Math.floor(randomBetween(min, max + 1, rng));
    }

    function clamp(value, min, max) {
        return Math.min(Math.max(value, min), max);
    }

    function createSvgElement(name, attrs = {}) {
        const el = document.createElementNS(NS, name);
        Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, value));
        return el;
    }

    function getDocumentHeight() {
        return Math.max(
            document.body.scrollHeight,
            document.documentElement.scrollHeight,
            window.innerHeight
        );
    }

    function getDirectionWeights(maxWidth, maxHeight) {
        const aspect = maxHeight / Math.max(maxWidth, 1);
        const verticalBias = clamp(
            (aspect - 1) * 0.055,
            0,
            config.maxVerticalBias
        );

        return {
            horizontal: 0.38 - verticalBias * 0.45,
            vertical: 0.38 + verticalBias,
            diagonal: 0.24 - verticalBias * 0.55
        };
    }

    function chooseDirection(weights, previousDirection) {
        let candidates = [
            { key: "H", weight: weights.horizontal },
            { key: "V", weight: weights.vertical },
            { key: "D45", weight: weights.diagonal }
        ];

        if (previousDirection) {
            candidates = candidates.map((item) => ({
                ...item,
                weight: item.key === previousDirection
                    ? item.weight * 0.52
                    : item.weight
            }));
        }

        const total = candidates.reduce((sum, item) => sum + item.weight, 0);
        let pick = randomBetween(0, total);

        for (const item of candidates) {
            pick -= item.weight;
            if (pick <= 0) return item.key;
        }

        return candidates[candidates.length - 1].key;
    }

    function shuffleInPlace(items) {
        for (let i = items.length - 1; i > 0; i--) {
            const j = Math.floor(visualRandom() * (i + 1));
            [items[i], items[j]] = [items[j], items[i]];
        }
        return items;
    }

    function stratifiedY(index, count, maxHeight) {
        const usableHeight = Math.max(maxHeight - 60, 1);
        const bandHeight = usableHeight / Math.max(count, 1);
        const jitter = randomBetween(config.startJitterMin, config.startJitterMax);
        return clamp(30 + (index + jitter) * bandHeight, 30, maxHeight - 30);
    }

    function buildStartPoints(count, maxWidth, maxHeight) {
        const starts = [];
        let edgeCount = Math.round(count * config.edgeStartFraction);

        // Keep the edge population balanced so one side cannot win by chance.
        edgeCount = Math.min(count, Math.max(2, edgeCount));
        const leftCount = Math.ceil(edgeCount / 2);
        const rightCount = edgeCount - leftCount;

        for (let i = 0; i < leftCount; i++) {
            starts.push({
                x: randomBetween(-40, 92),
                y: stratifiedY(i, leftCount, maxHeight),
                preferredX: 1
            });
        }

        for (let i = 0; i < rightCount; i++) {
            starts.push({
                x: randomBetween(maxWidth - 92, maxWidth + 40),
                y: stratifiedY(i, rightCount, maxHeight),
                preferredX: -1
            });
        }

        const interiorCount = count - edgeCount;
        if (interiorCount > 0) {
            const pageAspect = maxWidth / Math.max(maxHeight, 1);
            const columns = clamp(
                Math.round(Math.sqrt(interiorCount * pageAspect)),
                2,
                6
            );
            const rows = Math.ceil(interiorCount / columns);
            const cellWidth = maxWidth / columns;
            const cellHeight = maxHeight / rows;
            const cells = [];

            for (let row = 0; row < rows; row++) {
                for (let column = 0; column < columns; column++) {
                    cells.push({ row, column });
                }
            }

            shuffleInPlace(cells);

            for (let i = 0; i < interiorCount; i++) {
                const { row, column } = cells[i];
                const x = clamp(
                    (column + randomBetween(config.startJitterMin, config.startJitterMax)) * cellWidth,
                    20,
                    maxWidth - 20
                );
                const y = clamp(
                    (row + randomBetween(config.startJitterMin, config.startJitterMax)) * cellHeight,
                    20,
                    maxHeight - 20
                );

                starts.push({
                    x,
                    y,
                    // Favor travel toward the page center when already near a side.
                    preferredX: x < maxWidth * 0.35
                        ? 1
                        : x > maxWidth * 0.65
                            ? -1
                            : (visualRandom() > 0.5 ? 1 : -1)
                });
            }
        }

        return shuffleInPlace(starts);
    }

    function buildPath(startX, startY, maxWidth, maxHeight, preferredXHint = null) {
        const points = [[startX, startY]];
        const weights = getDirectionWeights(maxWidth, maxHeight);

        let x = startX;
        let y = startY;
        let previousDirection = null;

        const segmentCount = randomInt(6, 12);
        const preferredX = preferredXHint ?? (visualRandom() > 0.5 ? 1 : -1);
        const preferredY = startY < maxHeight * 0.18
            ? 1
            : startY > maxHeight * 0.82
                ? -1
                : (visualRandom() > 0.35 ? 1 : -1);

        for (let i = 0; i < segmentCount; i++) {
            const direction = chooseDirection(weights, previousDirection);
            const xDirection = visualRandom() > 0.28 ? preferredX : -preferredX;
            const yDirection = visualRandom() > 0.24 ? preferredY : -preferredY;

            if (direction === "H") {
                x += randomBetween(
                    config.horizontalSpacing * 0.55,
                    config.horizontalSpacing * 1.75
                ) * xDirection;
            } else if (direction === "V") {
                y += randomBetween(
                    config.verticalSpacing * 0.55,
                    config.verticalSpacing * 1.9
                ) * yDirection;
            } else {
                // Strict 45-degree routing: |dx| === |dy|.
                const distance = randomBetween(38, 112);
                x += distance * xDirection;
                y += distance * yDirection;
            }

            x = clamp(x, -90, maxWidth + 90);
            y = clamp(y, 0, maxHeight);

            const [px, py] = points[points.length - 1];
            const dx = x - px;
            const dy = y - py;

            // Clamping at the document boundary can spoil a 45° segment.
            // Snap the endpoint back to H/V/45 instead of allowing arbitrary angles.
            if (direction === "D45" && Math.abs(Math.abs(dx) - Math.abs(dy)) > 0.01) {
                const magnitude = Math.min(Math.abs(dx), Math.abs(dy));

                if (magnitude < 10) {
                    if (Math.abs(dx) >= Math.abs(dy)) {
                        y = py;
                    } else {
                        x = px;
                    }
                } else {
                    x = px + Math.sign(dx || xDirection) * magnitude;
                    y = py + Math.sign(dy || yDirection) * magnitude;
                }
            }

            if (Math.abs(x - px) < 1 && Math.abs(y - py) < 1) continue;

            points.push([x, y]);
            previousDirection = direction;
        }

        return points;
    }

    function pointsToPath(points) {
        if (!points.length) return "";
        const [first, ...rest] = points;

        return `M ${first[0].toFixed(1)} ${first[1].toFixed(1)} ` +
            rest.map(([x, y]) => `L ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    }

    function addPads(group, points, toneClass) {
        const candidates = [points[0], points[points.length - 1]];

        if (points.length > 5 && visualRandom() > 0.32) {
            candidates.push(points[randomInt(1, points.length - 2)]);
        }

        candidates.forEach(([x, y]) => {
            group.appendChild(createSvgElement("circle", {
                cx: x,
                cy: y,
                r: visualRandom() > 0.77 ? 4.2 : 3.1,
                class: `circuit-pad ${toneClass}`
            }));
        });
    }

    function addMicrochip(group, maxWidth, maxHeight) {
        if (visualRandom() < 0.40) return;

        const x = randomBetween(30, Math.max(31, maxWidth - 130));
        const y = randomBetween(120, Math.max(121, maxHeight - 160));
        const w = randomBetween(44, 76);
        const h = randomBetween(30, 54);

        const chip = createSvgElement("g", { class: "circuit-chip" });
        chip.appendChild(createSvgElement("rect", { x, y, width: w, height: h, rx: 3 }));

        for (let i = 0; i < 4; i++) {
            const py = y + 8 + i * ((h - 16) / 3);
            chip.appendChild(createSvgElement("line", { x1: x - 10, y1: py, x2: x, y2: py }));
            chip.appendChild(createSvgElement("line", { x1: x + w, y1: py, x2: x + w + 10, y2: py }));
        }

        group.appendChild(chip);
    }

    function buildSamples(path, totalLength) {
        const samples = [];
        const step = Math.max(18, config.sampleSpacing);

        for (let distance = 0; distance <= totalLength; distance += step) {
            const point = path.getPointAtLength(distance);
            samples.push({ x: point.x, y: point.y, length: distance });
        }

        if (samples.at(-1)?.length !== totalLength) {
            const point = path.getPointAtLength(totalLength);
            samples.push({ x: point.x, y: point.y, length: totalLength });
        }

        return samples;
    }

    function addMaskGradient(id, stops) {
        const gradient = createSvgElement("radialGradient", { id });

        for (const stop of stops) {
            gradient.appendChild(createSvgElement("stop", {
                offset: stop.offset,
                "stop-color": "white",
                "stop-opacity": stop.opacity
            }));
        }

        defs.appendChild(gradient);
    }

    function buildSharedMasks() {
        addMaskGradient("cursor-soft-fade", [
            { offset: "0%", opacity: "0.66" },
            { offset: "28%", opacity: "0.48" },
            { offset: "62%", opacity: "0.16" },
            { offset: "100%", opacity: "0" }
        ]);

        addMaskGradient("activity-soft-fade", [
            { offset: "0%", opacity: "1" },
            { offset: "24%", opacity: "0.88" },
            { offset: "55%", opacity: "0.35" },
            { offset: "82%", opacity: "0.09" },
            { offset: "100%", opacity: "0" }
        ]);

        const cursorMask = createSvgElement("mask", {
            id: "cursor-trace-mask",
            maskUnits: "userSpaceOnUse",
            x: 0,
            y: 0,
            width: viewportWidth,
            height: documentHeight
        });

        cursorMask.appendChild(createSvgElement("rect", {
            x: 0,
            y: 0,
            width: viewportWidth,
            height: documentHeight,
            fill: "black"
        }));

        cursorMaskCircle = createSvgElement("circle", {
            cx: -1000,
            cy: -1000,
            r: config.cursorRadius,
            fill: "url(#cursor-soft-fade)"
        });

        cursorMask.appendChild(cursorMaskCircle);
        defs.appendChild(cursorMask);
    }

    function buildCircuit() {
        clearTimeout(pulseTimer);
        cancelAnimationFrame(pulseAnimationFrame);
        pulseAnimationFrame = null;
        activePulses = [];

        host.innerHTML = "";
        paths = [];
        resetVisualRandom();

        viewportWidth = Math.max(window.innerWidth, 900);
        documentHeight = getDocumentHeight();

        svg = createSvgElement("svg", {
            class: "circuit-svg",
            viewBox: `0 0 ${viewportWidth} ${documentHeight}`,
            preserveAspectRatio: "none"
        });

        defs = createSvgElement("defs");

        const glow = createSvgElement("filter", {
            id: "circuit-glow",
            x: "-60%",
            y: "-60%",
            width: "220%",
            height: "220%"
        });
        glow.appendChild(createSvgElement("feGaussianBlur", {
            stdDeviation: "2.6",
            result: "blur"
        }));

        const merge = createSvgElement("feMerge");
        merge.appendChild(createSvgElement("feMergeNode", { in: "blur" }));
        merge.appendChild(createSvgElement("feMergeNode", { in: "SourceGraphic" }));
        glow.appendChild(merge);
        defs.appendChild(glow);

        buildSharedMasks();
        svg.appendChild(defs);

        const gridLayer = createSvgElement("g", { class: "circuit-grid" });
        const decorativeLayer = createSvgElement("g", { class: "circuit-decor" });
        traceLayer = createSvgElement("g", { class: "circuit-traces" });
        hoverLayer = createSvgElement("g", { class: "circuit-hover-layer" });
        pulseLayer = createSvgElement("g", { class: "circuit-pulses" });

        for (let x = 0; x <= viewportWidth; x += 128) {
            gridLayer.appendChild(createSvgElement("line", {
                x1: x, y1: 0, x2: x, y2: documentHeight
            }));
        }

        for (let y = 0; y <= documentHeight; y += 128) {
            gridLayer.appendChild(createSvgElement("line", {
                x1: 0, y1: y, x2: viewportWidth, y2: y
            }));
        }

        const pageLengthFactor = clamp(
            documentHeight / Math.max(window.innerHeight, 1),
            1,
            4
        );
        const countBoost = Math.round((pageLengthFactor - 1) * 4);
        const count = randomInt(
            config.pathCountMin + countBoost,
            config.pathCountMax + countBoost
        );

        const startPoints = buildStartPoints(count, viewportWidth, documentHeight);

        for (let i = 0; i < count; i++) {
            const start = startPoints[i];
            const pointList = buildPath(
                start.x,
                start.y,
                viewportWidth,
                documentHeight,
                start.preferredX
            );
            const d = pointsToPath(pointList);
            const toneClass = visualRandom() > 0.51
                ? "circuit-tone--purple"
                : "circuit-tone--gold";

            const path = createSvgElement("path", {
                d,
                class: `circuit-trace ${toneClass}`
            });

            traceLayer.appendChild(path);
            addPads(decorativeLayer, pointList, toneClass);

            const totalLength = path.getTotalLength();
            const midpoint = path.getPointAtLength(totalLength * 0.5);
            paths.push({
                path,
                d,
                toneClass,
                totalLength,
                anchor: { x: midpoint.x, y: midpoint.y },
                samples: buildSamples(path, totalLength)
            });
        }

        const chipCount = Math.max(3, Math.floor(documentHeight / 820));
        for (let i = 0; i < chipCount; i++) {
            addMicrochip(decorativeLayer, viewportWidth, documentHeight);
        }

        svg.append(gridLayer, decorativeLayer, traceLayer, hoverLayer, pulseLayer);
        host.appendChild(svg);

        updateParallax();
        attachReactiveSections();

        if (!prefersReducedMotion.matches) schedulePulse();
    }

    function schedulePulse() {
        clearTimeout(pulseTimer);

        const delay = randomBetween(
            config.pulseIntervalMin,
            config.pulseIntervalMax,
            Math.random
        );

        pulseTimer = setTimeout(() => {
            firePulseBurst();
            schedulePulse();
        }, delay);
    }

    function firePulseBurst() {
        if (!paths.length || prefersReducedMotion.matches) return;

        let burstCount = randomInt(
            config.pulseBurstMin,
            config.pulseBurstMax,
            Math.random
        );

        if (Math.random() > config.pulseBurstExtraChance) {
            burstCount = Math.min(burstCount, 2);
        }

        const choices = [...paths];
        const selected = [];
        const minimumSeparation = config.activityRadiusMax * 1.8;

        for (let i = 0; i < burstCount && choices.length; i++) {
            let eligible = choices;

            if (selected.length) {
                const separated = choices.filter((candidate) => {
                    return selected.every((picked) => {
                        const dx = candidate.anchor.x - picked.anchor.x;
                        const dy = candidate.anchor.y - picked.anchor.y;
                        return Math.hypot(dx, dy) >= minimumSeparation;
                    });
                });

                if (separated.length) eligible = separated;
            }

            const item = eligible[randomInt(0, eligible.length - 1, Math.random)];
            selected.push(item);
            choices.splice(choices.indexOf(item), 1);

            const delay = randomBetween(0, config.pulseStaggerMax, Math.random);
            window.setTimeout(() => startActivityPulse(item), delay);
        }
    }

    function startActivityPulse(item) {
        if (!item || prefersReducedMotion.matches) return;

        const pulseId = `activity-mask-${Date.now()}-${Math.floor(Math.random() * 1e8)}`;
        const mask = createSvgElement("mask", {
            id: pulseId,
            maskUnits: "userSpaceOnUse",
            x: 0,
            y: 0,
            width: viewportWidth,
            height: documentHeight
        });

        mask.appendChild(createSvgElement("rect", {
            x: 0,
            y: 0,
            width: viewportWidth,
            height: documentHeight,
            fill: "black"
        }));

        const radius = randomBetween(
            config.activityRadiusMin,
            config.activityRadiusMax,
            Math.random
        );

        const circle = createSvgElement("circle", {
            cx: -1000,
            cy: -1000,
            r: radius,
            fill: "url(#activity-soft-fade)"
        });

        mask.appendChild(circle);
        defs.appendChild(mask);

        const overlay = createSvgElement("path", {
            d: item.d,
            class: `circuit-activity-trace ${item.toneClass}`,
            mask: `url(#${pulseId})`
        });
        pulseLayer.appendChild(overlay);

        activePulses.push({
            item,
            mask,
            circle,
            overlay,
            reverse: Math.random() > 0.5,
            startedAt: performance.now(),
            duration: randomBetween(2800, 5600, Math.random)
        });

        ensurePulseAnimator();
    }

    function ensurePulseAnimator() {
        if (pulseAnimationFrame || !activePulses.length) return;
        pulseAnimationFrame = requestAnimationFrame(animatePulses);
    }

    function animatePulses(now) {
        pulseAnimationFrame = null;

        activePulses = activePulses.filter((pulse) => {
            const rawProgress = (now - pulse.startedAt) / pulse.duration;

            if (rawProgress >= 1) {
                pulse.overlay.remove();
                pulse.mask.remove();
                return false;
            }

            // Smooth acceleration/deceleration while preserving continuous travel.
            const eased = rawProgress < 0.5
                ? 2 * rawProgress * rawProgress
                : 1 - Math.pow(-2 * rawProgress + 2, 2) / 2;

            const progress = pulse.reverse ? 1 - eased : eased;
            const point = pulse.item.path.getPointAtLength(
                pulse.item.totalLength * progress
            );

            pulse.circle.setAttribute("cx", point.x.toFixed(2));
            pulse.circle.setAttribute("cy", point.y.toFixed(2));

            // Fade the whole effect in/out without changing the mask shape.
            const envelope = Math.sin(Math.PI * rawProgress);
            pulse.overlay.setAttribute("opacity", String(clamp(envelope * 0.92, 0, 0.92)));

            return true;
        });

        if (activePulses.length) {
            pulseAnimationFrame = requestAnimationFrame(animatePulses);
        }
    }

    function clearCursorHighlights() {
        hoverLayer?.replaceChildren();
        if (cursorMaskCircle) {
            cursorMaskCircle.setAttribute("cx", "-1000");
            cursorMaskCircle.setAttribute("cy", "-1000");
        }
    }

    function clientToSvg(clientX, clientY) {
        if (!svg) return null;

        const rect = svg.getBoundingClientRect();
        if (!rect.width || !rect.height) return null;

        return {
            x: (clientX - rect.left) * (viewportWidth / rect.width),
            y: (clientY - rect.top) * (documentHeight / rect.height)
        };
    }

    function nearestSample(item, point) {
        let nearest = null;
        let bestDistanceSquared = Infinity;

        for (const sample of item.samples) {
            const dx = sample.x - point.x;
            const dy = sample.y - point.y;
            const distanceSquared = dx * dx + dy * dy;

            if (distanceSquared < bestDistanceSquared) {
                bestDistanceSquared = distanceSquared;
                nearest = sample;
            }
        }

        return {
            sample: nearest,
            distance: Math.sqrt(bestDistanceSquared)
        };
    }

    function renderCursorHighlights(clientX, clientY) {
        const reactiveElement = document.elementFromPoint(clientX, clientY)
            ?.closest?.("[data-circuit-reactive]");

        if (!reactiveElement) {
            clearCursorHighlights();
            return;
        }

        const point = clientToSvg(clientX, clientY);
        if (!point) return;

        const matches = [];

        for (const item of paths) {
            const result = nearestSample(item, point);
            if (result.distance <= config.cursorRadius) {
                matches.push({ item, distance: result.distance });
            }
        }

        matches.sort((a, b) => a.distance - b.distance);
        const selected = matches.slice(0, config.cursorTraceLimit);

        hoverLayer.replaceChildren();
        cursorMaskCircle.setAttribute("cx", point.x.toFixed(2));
        cursorMaskCircle.setAttribute("cy", point.y.toFixed(2));

        for (const { item, distance } of selected) {
            const overlay = createSvgElement("path", {
                d: item.d,
                class: `circuit-cursor-trace ${item.toneClass}`,
                mask: "url(#cursor-trace-mask)"
            });

            const proximity = 1 - clamp(distance / config.cursorRadius, 0, 1);
            overlay.setAttribute("opacity", String(0.10 + proximity * 0.20));
            hoverLayer.appendChild(overlay);
        }
    }

    function attachReactiveSections() {
        document.querySelectorAll("[data-circuit-reactive]").forEach((section) => {
            if (section.dataset.circuitBound === "true") return;
            section.dataset.circuitBound = "true";

            section.addEventListener("pointerleave", clearCursorHighlights);
            section.addEventListener("focusout", (event) => {
                if (!section.contains(event.relatedTarget)) clearCursorHighlights();
            });
        });
    }

    function onPointerMove(event) {
        lastPointerEvent = event;
        if (pointerTicking) return;

        pointerTicking = true;
        requestAnimationFrame(() => {
            if (lastPointerEvent) {
                renderCursorHighlights(lastPointerEvent.clientX, lastPointerEvent.clientY);
            }
            pointerTicking = false;
        });
    }

    function updateParallax() {
        if (!svg) return;

        // Directly follow the browser's scroll position. There is no interpolation
        // or catch-up animation here, so the background never trails the content.
        const y = window.scrollY * config.parallaxFactor;
        svg.style.transform = `translate3d(0, ${y.toFixed(3)}px, 0)`;
    }

    function onScroll() {
        updateParallax();

        // The SVG's screen-space position changes with parallax, so refresh the
        // cursor-local lighting against the newly positioned trace field.
        if (lastPointerEvent) {
            renderCursorHighlights(
                lastPointerEvent.clientX,
                lastPointerEvent.clientY
            );
        }
    }

    function onResize() {
        clearTimeout(resizeTimer);

        resizeTimer = setTimeout(() => {
            const newHeight = getDocumentHeight();
            const widthChanged = Math.abs(window.innerWidth - viewportWidth) > 48;
            const heightChanged = Math.abs(newHeight - documentHeight) > 140;

            if (widthChanged || heightChanged) buildCircuit();
        }, 220);
    }

    prefersReducedMotion.addEventListener?.("change", () => {
        if (prefersReducedMotion.matches) {
            updateParallax();
            clearTimeout(pulseTimer);
            cancelAnimationFrame(pulseAnimationFrame);
            pulseAnimationFrame = null;
            activePulses.forEach((pulse) => {
                pulse.overlay.remove();
                pulse.mask.remove();
            });
            activePulses = [];
            clearCursorHighlights();
        } else {
            updateParallax();
            schedulePulse();
        }
    });

    document.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);

    window.addEventListener("load", () => {
        if (Math.abs(getDocumentHeight() - documentHeight) > 140) {
            buildCircuit();
        }
    });

    buildCircuit();
})();
