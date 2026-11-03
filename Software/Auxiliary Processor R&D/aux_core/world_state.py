from __future__ import annotations

"""Bounded, deterministic, anonymous scene cache; never a motion/safety authority.

Frame boxes are image-space YOLO detections. Track IDs are ephemeral and must not
be interpreted as biometric identity or a persistent guarantee of object identity.
"""

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0., x2 - x1) * max(0., y2 - y1)
    area_a = max(0., a[2] - a[0]) * max(0., a[3] - a[1])
    area_b = max(0., b[2] - b[0]) * max(0., b[3] - b[1])
    return overlap / (area_a + area_b - overlap) if area_a + area_b > overlap else 0.


class WorldState:
    def __init__(self, *, current_ms: int = 2500, retention_ms: int = 15000, max_tracks: int = 40,
                 match_iou: float = 0.25, min_confidence: float = 0.35) -> None:
        self.current_ms = max(250, int(current_ms))
        self.retention_ms = max(self.current_ms, int(retention_ms))
        self.max_tracks = max(1, int(max_tracks))
        self.match_iou = float(match_iou)
        self.min_confidence = float(min_confidence)
        self._lock = threading.RLock()
        self._tracks: dict[str, dict[str, Any]] = {}
        self._sequence = 0
        self._last_update = None
        self._source = None
        self._last_error = None
        self._inference_ms = None
        self._frames = 0

    def report_error(self, detail: str) -> None:
        with self._lock:
            self._last_error = str(detail)[:200]

    def update(self, detections: list[dict[str, Any]], *, camera_id: str, inference_ms: float | None = None,
               now: float | None = None) -> None:
        stamp = time.monotonic() if now is None else float(now)
        valid = []
        for det in detections:
            try:
                label = str(det['label']).strip().lower()[:64]
                score = float(det['confidence'])
                box = [float(x) for x in det['xyxy']]
                if (not label or score < self.min_confidence or len(box) != 4 or
                    not all(math.isfinite(v) for v in box) or box[2] <= box[0] or box[3] <= box[1]):
                    continue
                valid.append((label, score, box))
            except (ValueError, TypeError, KeyError):
                continue
        valid.sort(key=lambda d: d[1], reverse=True)
        with self._lock:
            for id_, item in list(self._tracks.items()):
                if 1000. * max(0., stamp - item['seen_mono']) > self.retention_ms:
                    del self._tracks[id_]
            unused = set(self._tracks)
            for label, score, box in valid[:self.max_tracks]:
                candidates = [( _iou(box, old['bbox_xyxy']), key) for key, old in self._tracks.items()
                              if key in unused and old['label'] == label and old['camera_id'] == camera_id]
                best = max(candidates, default=(0., None))
                if best[1] is not None and best[0] >= self.match_iou:
                    id_ = best[1]
                    unused.discard(id_)
                else:
                    self._sequence += 1
                    id_ = ('person' if label == 'person' else 'object') + '_' + str(self._sequence)
                previous = self._tracks.get(id_)
                cx = (box[0] + box[2]) / 2.
                cy = (box[1] + box[3]) / 2.
                movement = 0.
                if previous:
                    old = previous['bbox_xyxy']
                    movement = math.hypot(cx - (old[0]+old[2])/2., cy - (old[1]+old[3])/2.)
                self._tracks[id_] = {'id': id_, 'label': label, 'confidence': round(score, 3),
                                     'bbox_xyxy': [round(x, 1) for x in box], 'camera_id': camera_id,
                                     'seen_mono': stamp, 'movement_px': round(movement, 1),
                                     'first_seen_mono': previous['first_seen_mono'] if previous else stamp}
            if len(self._tracks) > self.max_tracks:
                oldest = sorted(self._tracks, key=lambda k: self._tracks[k]['seen_mono'])
                for key in oldest[:len(self._tracks) - self.max_tracks]:
                    del self._tracks[key]
            self._last_update = stamp
            self._source = str(camera_id)
            self._inference_ms = round(float(inference_ms), 1) if inference_ms is not None else None
            self._frames += 1
            self._last_error = None

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        stamp = time.monotonic() if now is None else float(now)
        with self._lock:
            items = []
            for item in self._tracks.values():
                age_ms = max(0, round((stamp - item['seen_mono']) * 1000))
                if age_ms > self.retention_ms:
                    continue
                items.append({k: v for k, v in item.items() if not k.endswith('_mono')} |
                             {'age_ms': age_ms, 'freshness': 'current' if age_ms <= self.current_ms else 'last_seen'})
            items.sort(key=lambda d: (d['freshness'] != 'current', d['age_ms'], d['id']))
            age = None if self._last_update is None else max(0, round((stamp-self._last_update)*1000))
            return {'schema': 'talus.world.v1', 'source': 'aux_yolo_anonymous', 'camera_id': self._source,
                    'observation_age_ms': age, 'status': 'unavailable' if age is None else
                    ('current' if age <= self.current_ms else 'stale'),
                    'tracks': items, 'current_count': sum(x['freshness']=='current' for x in items),
                    'person_count': sum(x['label']=='person' and x['freshness']=='current' for x in items),
                    'inference_ms': self._inference_ms, 'frames_processed': self._frames,
                    'last_error': self._last_error}

    def context(self, query: str, *, max_items: int = 10) -> str:
        """On-demand prompt fragment, not appended to every LLM turn."""
        q = query.casefold()
        # Explicit scene intent only: a generic "where" (e.g. campus offices)
        # must not attach environmental descriptions to unrelated questions.
        scene_phrases = ('can you see', 'do you see', 'did you see', 'what do you see',
                         'what did you see', 'what can you see', 'look at', 'on camera',
                         'in front of you', 'in this room', 'around me', 'near me',
                         'what am i holding', 'what am i showing', 'how many people',
                         'who is here', 'who is there', 'where did i leave',
                         'where did i put', 'where did you last see',
                         'what moved', 'which person', 'which object', 'last seen')
        relevant = any(phrase in q for phrase in scene_phrases)
        if not relevant and any(term in q for term in ('where is', 'where was', 'where are')):
            # Only resolve a location question from the scene if it mentions a
            # currently known detector class. No open-ended campus/place match.
            snap_for_match = self.snapshot()
            relevant = any(x['label'] in q for x in snap_for_match['tracks'])
        if not relevant:
            return ''
        snap = self.snapshot()
        if snap['status'] == 'unavailable':
            return '[Anonymous scene tracking] No deterministic background observation is available.'
        items = snap['tracks'][:max_items]
        lines = [f"{x['id']}: {x['label']}, confidence={x['confidence']}, "
                 f"box_px={x['bbox_xyxy']}, age_ms={x['age_ms']}, {x['freshness']}" for x in items]
        return ('[Deterministic scene tracks — not an image]\n'
                f"Scene status={snap['status']}; last detection age_ms={snap['observation_age_ms']}; "
                f"camera={snap['camera_id']}; image coordinates only.\n" +
                ('\n'.join(lines) if lines else 'No retained detections.') +
                '\nThese are approximate transient detector labels/boxes, not verified physical positions. '
                'Do not invent colors, actions, contact, object ownership, placement, depth, or visual details. '
                'Last_seen is historical and is not evidence the object remains there. '
                'For precise current visual details require a fresh camera image.')


class WorldObserver:
    """Low-rate read-only camera polling; skips work on unavailable Pi/model."""
    def __init__(self, pi: Any, detector: Any, world: WorldState, *, period_s: float = 3.0, ready_predicate=None):
        self.pi, self.detector, self.world = pi, detector, world
        self.period_s = max(0.5, float(period_s))
        self.ready_predicate = ready_predicate
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name='talus-world-observer', daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            tick = time.monotonic()
            try:
                if self.ready_predicate is not None and not self.ready_predicate():
                    self._stop.wait(0.25)
                    continue
                if self.detector.available():
                    frame, headers = self.pi.frame(view='raw')
                    if not frame:
                        raise ValueError('empty_camera_frame')
                    # Respect the Pi's freshness requirement; frame() enforces its age limit.
                    fetched_at = time.monotonic()
                    # Track capture freshness, not the time slow CPU inference ends.
                    # The Pi already enforces max_age_ms on the requested frame.
                    try:
                        age = max(0., min(60_000., float(headers.get('X-Automaton-Frame-Age-Ms', '0'))))
                    except (TypeError, ValueError):
                        age = 0.
                    captured_at = fetched_at - age / 1000.
                    result = self.detector.detect_jpeg(frame)
                    self.world.update(result, camera_id=headers.get('X-Automaton-Camera',
                                     self.pi.default_camera), inference_ms=(time.monotonic()-tick)*1000,
                                     now=captured_at)
                else:
                    self.world.report_error('object_detector_unavailable')
            except Exception as exc:
                self.world.report_error(type(exc).__name__ + ': ' + str(exc))
            self._stop.wait(max(0.05, self.period_s - (time.monotonic() - tick)))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.)
            self._thread = None
