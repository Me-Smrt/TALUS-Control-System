(() => {
    "use strict";

    const ui = {
        state: null,
        auxState: null,
        auxReachable: false,
        selectedCamera: null,
        view: "processed",
        stateTimer: null,
        frameTimer: null,
        auxStateTimer: null,
        auxHealthTimer: null,
        telemetryTimer: null,
        worldTimer: null,
        frameInFlight: false,
        framePending: false,
        frameObjectUrl: null,
    };

    const text = (selector, value) => {
        document.querySelectorAll(selector).forEach((el) => {
            el.textContent = value;
        });
    };

    const fmtNumber = (value, digits = 1, suffix = "") => {
        const n = Number(value);
        return Number.isFinite(n) ? `${n.toFixed(digits)}${suffix}` : "—";
    };

    const fmtDuration = (seconds) => {
        const n = Number(seconds);
        if (!Number.isFinite(n) || n < 0) return "—";
        const total = Math.floor(n);
        const days = Math.floor(total / 86400);
        const hours = Math.floor((total % 86400) / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        if (days) return `${days}d ${hours}h`;
        if (hours) return `${hours}h ${minutes}m`;
        return `${minutes}m`;
    };

    const fmtPercent = (value, digits = 0) => {
        const n = Number(value);
        return Number.isFinite(n) ? `${(n * 100).toFixed(digits)}%` : "—";
    };

    const fmtMegabytes = (value) => {
        const n = Number(value);
        if (!Number.isFinite(n)) return "—";
        return n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${n.toFixed(0)} MB`;
    };

    const boolWord = (value) => value === true ? "YES" : value === false ? "NO" : "UNKNOWN";
    const trackWord = (value) => value ? "TRACKING" : "—";

    const statusClass = (status, healthy = undefined) => {
        const s = String(status || "").toLowerCase();
        if (healthy === true || ["online", "healthy", "ok", "tracking", "ready"].includes(s)) return "ok";
        if (healthy === false || ["fault", "failed", "offline", "error"].includes(s)) return "bad";
        if (["starting", "warning", "degraded"].includes(s)) return "warn";
        return "unknown";
    };

    function setDot(el, status, healthy = undefined) {
        if (!el) return;
        el.classList.remove("status-dot--ok", "status-dot--bad", "status-dot--warn", "status-dot--unknown");
        el.classList.add(`status-dot--${statusClass(status, healthy)}`);
    }

    function renderCameraSelector(state) {
        const cameras = state?.cameras || {};
        const entries = Object.entries(cameras);
        document.querySelectorAll("[data-camera-selector]").forEach((container) => {
            const currentButtons = new Map(Array.from(container.querySelectorAll("button[data-camera-id]")).map((b) => [b.dataset.cameraId, b]));
            entries.forEach(([id, cam]) => {
                let button = currentButtons.get(id);
                if (!button) {
                    button = document.createElement("button");
                    button.type = "button";
                    button.dataset.cameraId = id;
                    button.addEventListener("click", () => {
                        ui.selectedCamera = id;
                        renderCameraSelector(ui.state);
                        refreshFrame(true);
                    });
                    container.appendChild(button);
                }
                button.textContent = cam.label || id;
                button.classList.toggle("is-active", id === ui.selectedCamera);
                button.setAttribute("aria-pressed", id === ui.selectedCamera ? "true" : "false");
                button.classList.toggle("is-offline", cam.status !== "online");
                button.title = `${cam.status || "unknown"}${cam.enabled === false ? " / disabled" : ""}`;
            });
            currentButtons.forEach((button, id) => {
                if (!cameras[id]) button.remove();
            });
        });
        if (!ui.selectedCamera && entries.length) {
            const online = entries.find(([, cam]) => cam.status === "online");
            ui.selectedCamera = (online || entries[0])[0];
            renderCameraSelector(state);
        }
    }

    function renderNodes(state) {
        const nodes = state?.control_nodes || {};
        let healthyCount = 0;
        let explicitFaults = 0;

        Object.entries(nodes).forEach(([id, node]) => {
            const marker = document.querySelector(`[data-node-marker="${id}"]`);
            if (marker) {
                marker.classList.remove("is-ok", "is-bad", "is-warn", "is-unknown");
                marker.classList.add(`is-${statusClass(node.status, node.healthy)}`);
                marker.title = `${node.label || id}: ${node.status || "unknown"}`;
            }
            if (node.healthy === true) healthyCount += 1;
            if (node.healthy === false || ["fault", "offline", "failed"].includes(String(node.status || "").toLowerCase())) explicitFaults += 1;
        });

        text("[data-ui='node-summary']", explicitFaults ? `${explicitFaults} FAULT` : (healthyCount ? `${healthyCount} HEALTHY` : "UNVERIFIED"));

        document.querySelectorAll("[data-node-list]").forEach((list) => {
            list.replaceChildren(...Object.entries(nodes).slice(0, 7).map(([id, node]) => {
                const row = document.createElement("div");
                row.className = "node-status-row";
                const left = document.createElement("span");
                const dot = document.createElement("i");
                dot.className = "status-dot";
                setDot(dot, node.status, node.healthy);
                const label = document.createElement("span");
                label.textContent = node.label || id;
                left.append(dot, label);
                const status = document.createElement("strong");
                status.className = "mono";
                status.textContent = String(node.status || "unknown").toUpperCase();
                row.append(left, status);
                return row;
            }));
        });

        document.querySelectorAll("[data-node-table]").forEach((table) => {
            table.replaceChildren(...Object.entries(nodes).map(([id, node]) => {
                const row = document.createElement("div");
                row.className = "node-table__row";
                const identity = document.createElement("div");
                identity.className = "node-table__identity";
                const dot = document.createElement("i");
                dot.className = "status-dot";
                setDot(dot, node.status, node.healthy);
                const labels = document.createElement("span");
                const strongLabel = document.createElement("strong");
                strongLabel.textContent = node.label || id;
                const roleLabel = document.createElement("small");
                roleLabel.textContent = node.role || "—";
                labels.append(strongLabel, roleLabel);
                identity.append(dot, labels);
                const stateCell = document.createElement("span");
                stateCell.className = "mono";
                stateCell.textContent = String(node.status || "unknown").toUpperCase();
                const channel = document.createElement("span");
                channel.className = "mono node-table__muted";
                channel.textContent = node.channel == null ? "CH —" : `CH ${node.channel}`;
                const iface = document.createElement("span");
                iface.className = "mono node-table__muted";
                iface.textContent = node.interface || "—";
                row.append(identity, stateCell, channel, iface);
                return row;
            }));
        });
    }

    function renderState(state) {
        ui.state = state;
        const system = state.system || {};
        const health = system.health || {};
        const safety = state.safety || {};
        const perception = state.perception || {};
        const motion = state.motion || {};
        const aux = state.auxiliary || {};
        const audio = state.audio || {};

        text("[data-ui='system-status']", String(system.status || "unknown").toUpperCase());
        text("[data-ui='system-health']", `CPU ${fmtNumber(health.cpu_percent, 0, "%")} / MEM ${fmtNumber(health.memory_percent, 0, "%")}`);
        text("[data-ui='safety-status']", safety.verified ? (safety.armed ? "ARMED" : "DISARMED") : "UNVERIFIED");
        text("[data-ui='safety-source']", safety.source || "—");
        text("[data-ui='perception-fps']", `${fmtNumber(perception.fps, 1)} FPS`);
        text("[data-ui='perception-summary']", `FACE ${trackWord(perception.face)} / BODY ${trackWord(perception.body)}`);
        // The Pi's auxiliary-link field is useful, but the dashboard also polls
        // the Aux service directly. Keep one composite top-level status so the
        // 1 Hz Pi refresh cannot overwrite a healthy direct Aux connection.
        renderCompositeAuxStatus();
        text("[data-ui='state-sequence']", `SEQ // ${state.sequence ?? "—"}`);
        text("[data-ui='last-update']", `STATE // ${state.generated_at_utc || "—"}`);

        text("[data-ui='armed']", boolWord(safety.armed));
        text("[data-ui='estop']", String(safety.estop || "unknown").toUpperCase());
        text("[data-ui='global-allow']", boolWord(safety.global_servo_allow));
        text("[data-ui='motion-status']", String(motion.status || "unknown").toUpperCase());
        text("[data-ui='motion-profile']", motion.simulation_profile || "—");
        text("[data-ui='safety-badge']", safety.verified ? "VERIFIED" : "UNVERIFIED");

        text("[data-ui='tracking-camera']", `CAM // ${perception.tracking_camera_id || "—"}`);
        text("[data-ui='face-track']", trackWord(perception.face));
        text("[data-ui='body-track']", trackWord(perception.body));
        text("[data-ui='left-hand-track']", trackWord(perception.hands?.left));
        text("[data-ui='right-hand-track']", trackWord(perception.hands?.right));
        text("[data-ui='perception-age']", perception.age_ms == null ? "—" : `${fmtNumber(perception.age_ms, 0)} ms`);

        text("[data-ui='cpu']", fmtNumber(health.cpu_percent, 1, "%"));
        text("[data-ui='memory']", fmtNumber(health.memory_percent, 1, "%"));
        text("[data-ui='temperature']", fmtNumber(health.cpu_temperature_c, 1, " °C"));
        text("[data-ui='microphone']", String(audio.input?.status || "unknown").toUpperCase());
        text("[data-ui='speaker']", String(audio.output?.status || "unknown").toUpperCase());
        text("[data-ui='aux-link']", String(aux.status || "not_connected").replace(/_/g, " ").toUpperCase());
        text("[data-ui='camera-count']", `CAMERAS // ${Object.keys(state.cameras || {}).length}`);
        renderPiMetrics(health, system);

        const sidebarDot = document.querySelector("[data-ui='sidebar-dot']");
        setDot(sidebarDot, system.status);
        text("[data-ui='sidebar-status']", system.status === "online" ? "Pi control plane online" : `Control plane ${system.status || "unknown"}`);
        text("[data-ui='sidebar-detail']", perception.status ? `Perception: ${perception.status}` : "Pi state API");

        renderCameraSelector(state);
        renderNodes(state);
        const collision = motion.summary?.collision || {};
        const simCollision = motion.summary?.simulation_collision || {};
        const gesture = motion.summary?.simulation_gesture || {};
        text("[data-ui='collision-status']", collision.blocked === true ? "HELD" :
            collision.blocked === false ? "PREVIEW CLEAR" : "UNVERIFIED");
        text("[data-ui='collision-clearance']", collision.min_clearance_mm == null ? "—" : `${fmtNumber(collision.min_clearance_mm,1)} mm`);
        text("[data-ui='simulation-clearance']", simCollision.min_clearance_mm == null ? "—" : `${fmtNumber(simCollision.min_clearance_mm,1)} mm`);
        text("[data-ui='collision-path']", collision.blocked === true ? "BLOCKED / HELD" : collision.blocked === false ? "CLEAR (APPROX)" : "—");
        text("[data-ui='simulation-gesture']", gesture.name ? `${gesture.name.toUpperCase()} / ${String(gesture.status || '').toUpperCase()}` : "IDLE");
    }

    function renderUnavailable(detail = "Pi state API unavailable") {
        text("[data-ui='system-status']", "OFFLINE");
        text("[data-ui='system-health']", detail);
        const dot = document.querySelector("[data-ui='sidebar-dot']");
        setDot(dot, "offline", false);
        text("[data-ui='sidebar-status']", "Control plane offline");
        text("[data-ui='sidebar-detail']", detail);
    }

    async function refreshState() {
        if (!document.querySelector("[data-robot-dashboard]")) return;
        try {
            const response = await fetch("/api/robot/state", {cache: "no-store", headers: {"Accept": "application/json"}});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
            renderState(payload);
        } catch (error) {
            renderUnavailable(error.message || "unavailable");
        }
    }

    function currentCamera() {
        if (!ui.state?.cameras) return null;
        if (ui.selectedCamera && ui.state.cameras[ui.selectedCamera]) return ui.selectedCamera;
        const entries = Object.entries(ui.state.cameras);
        const online = entries.find(([, cam]) => cam.status === "online");
        return (online || entries[0] || [null])[0];
    }

    async function waitForImageDecode(image) {
        if (typeof image.decode === "function") {
            try {
                await image.decode();
                return;
            } catch (_error) {
                // Older Safari/WebKit builds can reject decode() even though
                // the normal load event succeeds, so fall through.
            }
        }
        await new Promise((resolve, reject) => {
            if (image.complete && image.naturalWidth > 0) return resolve();
            image.addEventListener("load", resolve, {once: true});
            image.addEventListener("error", () => reject(new Error("frame_decode_failed")), {once: true});
        });
    }

    async function refreshFrame(force = false) {
        const camera = currentCamera();
        const images = document.querySelectorAll("[data-vision-image]");
        if (!camera || !images.length || document.hidden) return;
        if (ui.frameInFlight) {
            ui.framePending = ui.framePending || force;
            return;
        }

        const requestedView = ui.view;
        const requestKey = `${camera}:${requestedView}`;
        const camState = ui.state?.cameras?.[camera];
        const empty = document.querySelectorAll("[data-vision-empty]");
        text("[data-ui='camera-label']", `CAMERA // ${camState?.label || camera}`);

        ui.frameInFlight = true;
        try {
            const src = `/api/robot/cameras/${encodeURIComponent(camera)}/frame?view=${requestedView}&_=${Date.now()}`;
            const response = await fetch(src, {cache: "no-store", headers: {"Accept": "image/jpeg"}});
            if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try { const payload = await response.json(); detail = payload.detail || payload.error || detail; } catch (_error) { /* image/error response */ }
                throw new Error(detail);
            }
            const blob = await response.blob();
            if (!blob.size || (!blob.type.startsWith("image/") && blob.type !== "application/octet-stream")) {
                throw new Error("invalid_camera_frame");
            }

            // Decode the next JPEG off-screen first. The currently displayed
            // frame stays untouched until the replacement is fully present,
            // eliminating the blank flash between snapshot requests.
            const objectUrl = URL.createObjectURL(blob);
            const preloader = new Image();
            preloader.decoding = "async";
            preloader.src = objectUrl;
            try {
                await waitForImageDecode(preloader);
            } catch (error) {
                URL.revokeObjectURL(objectUrl);
                throw error;
            }

            if (`${currentCamera()}:${ui.view}` !== requestKey) {
                URL.revokeObjectURL(objectUrl);
                return;
            }

            const previous = ui.frameObjectUrl;
            images.forEach((img) => {
                img.src = objectUrl;
                img.hidden = false;
            });
            empty.forEach((el) => { el.hidden = true; });
            ui.frameObjectUrl = objectUrl;
            if (previous && previous !== objectUrl) {
                window.setTimeout(() => URL.revokeObjectURL(previous), 750);
            }

            const headerAgeRaw = response.headers.get("X-Automaton-Frame-Age-Ms");
            const headerAge = headerAgeRaw == null ? NaN : Number(headerAgeRaw);
            if (Number.isFinite(headerAge)) {
                text("[data-ui='frame-age']", `AGE // ${headerAge.toFixed(0)} ms`);
            } else if (camState?.captured_monotonic_ns && ui.state?.generated_monotonic_ns) {
                const age = Math.max(0, (ui.state.generated_monotonic_ns - camState.captured_monotonic_ns) / 1e6);
                text("[data-ui='frame-age']", `AGE // ${age.toFixed(0)} ms`);
            } else {
                text("[data-ui='frame-age']", "AGE // —");
            }
        } catch (_error) {
            // A transient failed snapshot must never erase a good frame. Only
            // show the empty state before the first successfully decoded frame.
            if (!ui.frameObjectUrl) {
                images.forEach((img) => { img.hidden = true; });
                empty.forEach((el) => { el.hidden = false; });
            }
        } finally {
            ui.frameInFlight = false;
            if (ui.framePending) {
                ui.framePending = false;
                window.setTimeout(() => refreshFrame(true), 0);
            }
        }
    }


    async function refreshWorldState() {
        if (!document.querySelector("[data-robot-dashboard]")) return;
        const [aux, pi] = await Promise.all([
            fetch("/api/aux/world", {cache: "no-store"}).then(r => {if (!r.ok) throw Error("aux_unavailable"); return r.json();}).catch(() => null),
            fetch("/api/robot/world", {cache: "no-store"}).then(r => {if (!r.ok) throw Error("pi_unavailable"); return r.json();}).catch(() => null),
        ]);
        text("[data-ui='world-status']", String(aux?.status || "UNAVAILABLE").toUpperCase());
        text("[data-ui='world-people']", aux?.person_count ?? "—");
        text("[data-ui='world-tracks']", aux?.current_count ?? "—");
        text("[data-ui='world-age']", aux?.observation_age_ms == null ? "—" : `${aux.observation_age_ms} ms`);
        text("[data-ui='world-inference']", aux?.inference_ms == null ? "—" : `${aux.inference_ms} ms`);
        text("[data-ui='pi-world-pose']", pi?.primary_subjects?.length ? "TRACKING" : "—");
        document.querySelectorAll("[data-world-track-list]").forEach(container => {
            container.replaceChildren();
            const tracks = Array.isArray(aux?.tracks) ? aux.tracks.slice(0, 12) : [];
            if (!tracks.length) {
                const empty = document.createElement("span");
                empty.className = "mono node-table__muted";
                empty.textContent = aux?.last_error ? `Tracker: ${String(aux.last_error).slice(0,100)}` : "No tracked items";
                container.appendChild(empty);
                return;
            }
            tracks.forEach(track => {
                const line = document.createElement("div");
                line.className = "node-table__row";
                const label = document.createElement("span");
                label.textContent = `${track.id} · ${track.label}`;
                const detail = document.createElement("span");
                detail.className = "mono node-table__muted";
                detail.textContent = `${track.freshness || "unknown"} · ${track.age_ms ?? "—"} ms`;
                line.append(label, detail);
                container.appendChild(line);
            });
        });
    }

    function renderCompositeAuxStatus() {
        const piAux = ui.state?.auxiliary || {};
        if (ui.auxReachable && ui.auxState) {
            const directStatus = String(ui.auxState.status || "online").toLowerCase();
            const label = directStatus === "online" ? "ONLINE" : directStatus.replace(/_/g, " ").toUpperCase();
            text("[data-ui='aux-status']", label);
            text("[data-ui='aux-type']", `AUX v${ui.auxState.service_version || "—"} · DIRECT API`);
            return;
        }
        text("[data-ui='aux-status']", String(piAux.status || "unknown").replace(/_/g, " ").toUpperCase());
        text("[data-ui='aux-type']", piAux.planned_type || "Auxiliary processor");
    }

    function renderPiMetrics(health, system) {
        text("[data-ui='pi-metric-cpu']", fmtNumber(health?.cpu_percent, 1, "%"));
        text("[data-ui='pi-metric-memory']", fmtNumber(health?.memory_percent, 1, "%"));
        text("[data-ui='pi-metric-disk']", fmtNumber(health?.disk_percent, 1, "%"));
        text("[data-ui='pi-metric-temp']", fmtNumber(health?.cpu_temperature_c, 1, " °C"));
        text("[data-ui='pi-metric-load']", fmtNumber(health?.load_1m, 2));
        text("[data-ui='pi-metric-rss']", fmtMegabytes(health?.process_rss_mb));
        text("[data-ui='pi-metric-uptime']", `UPTIME // ${fmtDuration(system?.uptime_s)}`);
        const used = fmtMegabytes(health?.memory_used_mb);
        text("[data-ui='pi-metric-detail']", used === "—" ? "HEALTH // LIVE" : `MEM USED // ${used}`);
        text("[data-ui='pi-metrics-badge']", `PI // ${String(system?.status || "unknown").toUpperCase()}`);
        if (String(system?.status || "").toLowerCase() === "online") {
            text("[data-ui='compute-badge']", ui.auxReachable ? "PI + AUX // LIVE" : "PI // LIVE");
        }
    }

    function renderAuxHealth(payload) {
        const health = payload?.system || payload?.health || {};
        text("[data-ui='aux-metric-cpu']", fmtNumber(health.cpu_percent, 1, "%"));
        text("[data-ui='aux-metric-memory']", fmtNumber(health.memory_percent, 1, "%"));
        text("[data-ui='aux-metric-disk']", fmtNumber(health.disk_percent, 1, "%"));
        text("[data-ui='aux-metric-temp']", fmtNumber(health.cpu_temperature_c, 1, " °C"));
        text("[data-ui='aux-metric-load']", fmtNumber(health.load_1m, 2));
        text("[data-ui='aux-metric-rss']", fmtMegabytes(health.process_rss_mb));
        text("[data-ui='aux-metric-uptime']", `UPTIME // ${fmtDuration(payload?.uptime_s)}`);
        const used = fmtMegabytes(health.memory_used_mb);
        const detail = used !== "—" ? `MEM USED // ${used}` : (health.platform ? `HOST // ${health.platform}` : "HEALTH // LIVE");
        text("[data-ui='aux-metric-detail']", detail);
        text("[data-ui='aux-metrics-badge']", `AUX // ${String(payload?.status || "online").toUpperCase()}`);
        text("[data-ui='compute-badge']", ui.state?.system?.status === "online" ? "PI + AUX // LIVE" : "AUX // LIVE");
    }

    async function refreshAuxHealth() {
        if (!document.querySelector("[data-hardware-metrics]")) return;
        try {
            const response = await fetch("/api/aux/health", {cache: "no-store", headers: {"Accept": "application/json"}});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
            renderAuxHealth(payload);
        } catch (_error) {
            ["aux-metric-cpu", "aux-metric-memory", "aux-metric-disk", "aux-metric-temp", "aux-metric-load", "aux-metric-rss"].forEach((key) => text(`[data-ui='${key}']`, "—"));
            text("[data-ui='aux-metric-uptime']", "UPTIME // —");
            text("[data-ui='aux-metric-detail']", "HEALTH // UNAVAILABLE");
            text("[data-ui='aux-metrics-badge']", "AUX // OFFLINE");
            text("[data-ui='compute-badge']", ui.state?.system?.status === "online" ? "PI // LIVE" : "OFFLINE");
        }
    }

    function renderTelemetry(payload) {
        const averages = payload?.averages || {};
        const rates = payload?.rates || {};
        const latest = payload?.latest_turn || {};
        const llm = latest?.llm || {};
        const turns = Number(payload?.window_turns || 0);
        text("[data-ui='telemetry-window']", `${turns} TURN${turns === 1 ? "" : "S"}`);
        text("[data-ui='perf-tps']", fmtNumber(averages.tokens_per_second, 1));
        text("[data-ui='perf-ttft']", fmtNumber(averages.llm_ttft_ms, 0));
        text("[data-ui='perf-turn']", fmtNumber(averages.turn_ms, 0));
        text("[data-ui='perf-tokens']", fmtNumber(averages.completion_tokens, 0));
        text("[data-ui='perf-rag-hit']", fmtPercent(rates.rag_hit_when_attempted));
        text("[data-ui='perf-deep']", fmtPercent(rates.deep_reasoning));
        text("[data-ui='perf-vision']", fmtPercent(rates.vision_used));
        text("[data-ui='perf-stt-rtf']", fmtNumber(averages.stt_rtf, 2));
        text("[data-ui='perf-last-mode']", `MODE // ${String(latest.reasoning_mode || "—").toUpperCase()}`);
        const inputLang = latest.input_language || "—";
        const outputLang = latest.output_language || "—";
        text("[data-ui='perf-last-lang']", `LANG // ${inputLang}→${outputLang}`.toUpperCase());
        const sources = Array.isArray(latest.rag_sources) ? latest.rag_sources : [];
        text("[data-ui='perf-last-rag']", `RAG // ${latest.rag_hits || 0}${sources.length ? ` · ${sources[0]}` : ""}`);
        text("[data-ui='perf-last-finish']", `FINISH // ${String(llm.finish_reason || "—").toUpperCase()}`);
    }

    async function refreshTelemetry() {
        if (!document.querySelector("[data-performance-telemetry]")) return;
        try {
            const response = await fetch("/api/aux/telemetry", {cache: "no-store", headers: {"Accept": "application/json"}});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
            renderTelemetry(payload);
        } catch (_error) {
            text("[data-ui='telemetry-window']", "OFFLINE");
            ["perf-tps", "perf-ttft", "perf-turn", "perf-tokens", "perf-rag-hit", "perf-deep", "perf-vision", "perf-stt-rtf"].forEach((key) => text(`[data-ui='${key}']`, "—"));
            text("[data-ui='perf-last-mode']", "MODE // —");
            text("[data-ui='perf-last-lang']", "LANG // —");
            text("[data-ui='perf-last-rag']", "RAG // —");
            text("[data-ui='perf-last-finish']", "FINISH // —");
        }
    }

    function csrfToken() {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
    }

    function renderAuxState(state) {
        ui.auxState = state;
        ui.auxReachable = true;
        const components = state?.components || {};
        const conversation = state?.conversation || {};
        const serviceStatus = String(state?.status || "online").toLowerCase();
        const online = serviceStatus === "online";
        text("[data-ui='aux-runtime-badge']", serviceStatus.replace(/_/g, " ").toUpperCase());
        text("[data-ui='aux-llm']", String(components.llm || "unknown").toUpperCase());
        text("[data-ui='aux-stt']", String(components.stt || "unknown").toUpperCase());
        text("[data-ui='aux-tts']", String(components.tts || "unknown").toUpperCase());
        text("[data-ui='aux-vision']", String(components.vision || "unknown").toUpperCase());
        text("[data-ui='aux-pi-link']", String(components.pi_link || "unknown").toUpperCase());
        text("[data-ui='aux-conversation']", String(conversation.state || "idle").toUpperCase());
        if (!online && serviceStatus === "starting") {
            text("[data-ui='aux-runtime-badge']", "STARTING");
        }
        renderCompositeAuxStatus();
    }

    async function refreshAuxState() {
        if (!document.querySelector("[data-aux-dashboard]")) return;
        try {
            const response = await fetch("/api/aux/status", {cache: "no-store", headers: {"Accept": "application/json"}});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
            renderAuxState(payload);
        } catch (_error) {
            ui.auxReachable = false;
            ui.auxState = null;
            text("[data-ui='aux-runtime-badge']", "OFFLINE");
            ["aux-llm", "aux-stt", "aux-tts", "aux-vision", "aux-pi-link", "aux-conversation"].forEach((key) => text(`[data-ui='${key}']`, "—"));
            renderCompositeAuxStatus();
        }
    }

    async function refreshVoiceSets() {
        const select = document.querySelector("[data-voice-set-select]");
        if (!select) return;
        try {
            const response = await fetch("/api/aux/voices", {cache: "no-store", headers: {"Accept": "application/json"}});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
            const sets = Array.isArray(payload.voice_sets) ? payload.voice_sets : [];
            const voices = Array.isArray(payload.voices) ? payload.voices : [];
            select.replaceChildren(...sets.map((voiceSet) => {
                const option = document.createElement("option");
                option.value = voiceSet.id;
                const exact = Number(voiceSet.exact_language_count || 0);
                const total = Number(voiceSet.total_language_count || 0);
                const usable = Number(voiceSet.available_language_count || 0);
                const suffix = total ? ` — ${exact}/${total} exact, ${usable}/${total} usable` : "";
                option.textContent = `${voiceSet.display_name || voiceSet.id}${suffix}`;
                option.selected = voiceSet.id === payload.active_voice_set_id;
                return option;
            }));
            select.disabled = sets.length === 0;
            const active = sets.find((voiceSet) => voiceSet.id === payload.active_voice_set_id) || sets[0];
            if (active) {
                const exact = Number(active.exact_language_count || 0);
                const total = Number(active.total_language_count || 0);
                const usable = Number(active.available_language_count || 0);
                text("[data-ui='voice-set-coverage']", `COVERAGE // ${exact}/${total} EXACT · ${usable}/${total} USABLE`);
                if (!payload.active_voice_set_id && active.id) select.value = active.id;
            } else {
                text("[data-ui='voice-set-coverage']", "COVERAGE // —");
            }
            text("[data-ui='tts-status']", voices.some((v) => v.available) ? "TTS // READY" : "TTS // MODELS MISSING");
        } catch (_error) {
            select.replaceChildren(new Option("Auxiliary service unavailable", ""));
            select.disabled = true;
            text("[data-ui='voice-set-coverage']", "COVERAGE // OFFLINE");
            text("[data-ui='tts-status']", "TTS // OFFLINE");
        }
    }

    async function waitForAudioReady(audio) {
        if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) return;
        await new Promise((resolve, reject) => {
            const timer = window.setTimeout(() => reject(new Error("audio_load_timeout")), 5000);
            const done = (fn) => () => {
                window.clearTimeout(timer);
                audio.removeEventListener("loadedmetadata", onReady);
                audio.removeEventListener("canplay", onReady);
                audio.removeEventListener("error", onError);
                fn();
            };
            const onReady = done(resolve);
            const onError = done(() => reject(new Error("audio_decode_failed")));
            audio.addEventListener("loadedmetadata", onReady, {once: true});
            audio.addEventListener("canplay", onReady, {once: true});
            audio.addEventListener("error", onError, {once: true});
        });
    }

    function bindVoiceControls() {
        const select = document.querySelector("[data-voice-set-select]");
        const preview = document.querySelector("[data-voice-preview]");
        const sample = document.querySelector("[data-voice-sample]");
        const audio = document.querySelector("[data-voice-audio]");
        if (!select || !preview || !sample || !audio) return;

        select.addEventListener("change", async () => {
            const voiceSetId = select.value;
            if (!voiceSetId) return;
            try {
                const response = await fetch("/api/aux/voice-set/select", {
                    method: "POST",
                    headers: {"Accept": "application/json", "Content-Type": "application/json", "X-CSRFToken": csrfToken()},
                    body: JSON.stringify({voice_set_id: voiceSetId}),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
                text("[data-ui='voice-feedback']", "VOICE SET // SELECTED");
                await refreshVoiceSets();
            } catch (error) {
                text("[data-ui='voice-feedback']", `VOICE SET // ${String(error.message || "ERROR").toUpperCase()}`);
                refreshVoiceSets();
            }
        });

        preview.addEventListener("click", async () => {
            const value = sample.value.trim();
            if (!value) return;
            preview.disabled = true;
            text("[data-ui='voice-feedback']", "SYNTH // WORKING");
            try {
                const response = await fetch("/api/aux/tts/sample", {
                    method: "POST",
                    headers: {"Accept": "audio/wav", "Content-Type": "application/json", "X-CSRFToken": csrfToken()},
                    body: JSON.stringify({text: value, voice_set_id: select.value || undefined}),
                });
                if (!response.ok) {
                    let detail = `HTTP ${response.status}`;
                    try { const payload = await response.json(); detail = payload.detail || payload.error || detail; } catch (_e) { /* audio/error response */ }
                    throw new Error(detail);
                }
                const blob = await response.blob();
                if (blob.size < 44) throw new Error("EMPTY OR INVALID WAV");
                const oldUrl = audio.dataset.objectUrl || "";
                const url = URL.createObjectURL(blob);
                audio.dataset.objectUrl = url;
                audio.src = url;
                audio.load();
                await waitForAudioReady(audio);
                await audio.play();
                if (oldUrl) URL.revokeObjectURL(oldUrl);
                const selectedVoice = response.headers.get("X-Automaton-Voice-Id");
                text(
                    "[data-ui='voice-feedback']",
                    selectedVoice ? `SYNTH // PLAYING · ${selectedVoice}` : "SYNTH // PLAYING",
                );
            } catch (error) {
                text("[data-ui='voice-feedback']", `SYNTH // ${String(error.message || "ERROR").toUpperCase()}`);
            } finally {
                preview.disabled = false;
            }
        });
        audio.addEventListener("ended", () => text("[data-ui='voice-feedback']", "READY // COMPLETE"));
    }

    function bindControls() {
        document.querySelectorAll("[data-frame-view]").forEach((button) => {
            button.setAttribute("aria-pressed", button.classList.contains("is-active") ? "true" : "false");
            button.addEventListener("click", () => {
                ui.view = button.dataset.frameView || "processed";
                document.querySelectorAll("[data-frame-view]").forEach((peer) => {
                    const active = peer === button;
                    peer.classList.toggle("is-active", active);
                    peer.setAttribute("aria-pressed", active ? "true" : "false");
                });
                refreshFrame(true);
            });
        });
    }

    function bindMobileNavigation() {
        const header = document.querySelector(".site-header");
        const toggle = document.querySelector("[data-nav-toggle]");
        const nav = document.querySelector("[data-primary-nav]");
        if (!header || !toggle || !nav) return;

        const mobileQuery = window.matchMedia("(max-width: 860px)");

        const setOpen = (open, {restoreFocus = false} = {}) => {
            const shouldOpen = Boolean(open && mobileQuery.matches);
            header.dataset.navOpen = shouldOpen ? "true" : "false";
            toggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");

            if (!shouldOpen && restoreFocus) {
                toggle.focus({preventScroll: true});
            }
        };

        toggle.addEventListener("click", () => {
            setOpen(toggle.getAttribute("aria-expanded") !== "true");
        });

        nav.addEventListener("click", (event) => {
            if (event.target.closest("a")) setOpen(false);
        });

        document.addEventListener("pointerdown", (event) => {
            if (toggle.getAttribute("aria-expanded") !== "true") return;
            if (!header.contains(event.target)) setOpen(false);
        });

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
                setOpen(false, {restoreFocus: true});
            }
        });

        const syncForViewport = () => {
            if (!mobileQuery.matches) setOpen(false);
        };

        mobileQuery.addEventListener?.("change", syncForViewport);
        window.addEventListener("pageshow", () => setOpen(false));
    }

    function centerActiveDashboardTab() {
        const nav = document.querySelector("[data-dashboard-nav]");
        const active = nav?.querySelector("a.is-active");
        if (!nav || !active || !window.matchMedia("(max-width: 860px)").matches) return;

        requestAnimationFrame(() => {
            const target = active.offsetLeft - (nav.clientWidth - active.offsetWidth) / 2;
            nav.scrollLeft = Math.max(0, target);
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        const currentPath = window.location.pathname;
        document.querySelectorAll(".site-nav a").forEach((link) => {
            const href = link.getAttribute("href");
            if (href && href !== "/" && currentPath === href) {
                link.classList.add("is-active");
                link.setAttribute("aria-current", "page");
            }
        });

        bindMobileNavigation();
        centerActiveDashboardTab();
        bindControls();
        bindVoiceControls();
        if (document.querySelector("[data-robot-dashboard]")) {
            refreshState().then(() => refreshFrame(true));
            refreshWorldState();
            ui.stateTimer = window.setInterval(refreshState, 1000);
            ui.frameTimer = window.setInterval(refreshFrame, 500);
            refreshAuxState();
            refreshAuxHealth();
            refreshTelemetry();
            refreshVoiceSets();
            ui.auxStateTimer = window.setInterval(refreshAuxState, 2000);
            ui.auxHealthTimer = window.setInterval(refreshAuxHealth, 2500);
            ui.telemetryTimer = window.setInterval(refreshTelemetry, 2500);
            ui.worldTimer = window.setInterval(refreshWorldState, 2500);
            window.setInterval(refreshVoiceSets, 15000);
        }
    });

    window.addEventListener("beforeunload", () => {
        if (ui.frameObjectUrl) URL.revokeObjectURL(ui.frameObjectUrl);
        const audio = document.querySelector("[data-voice-audio]");
        if (audio?.dataset.objectUrl) URL.revokeObjectURL(audio.dataset.objectUrl);
    });
})();
