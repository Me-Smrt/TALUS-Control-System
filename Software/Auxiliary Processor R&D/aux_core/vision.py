from __future__ import annotations
from pathlib import Path
from typing import Any
import threading

class UltralyticsDetector:
    def __init__(self,cfg:dict[str,Any],root:Path):
        self.cfg=dict(cfg); p=Path(str(cfg.get("model_path",""))); self.path=p if p.is_absolute() else (root/p).resolve(); self._model=None; self._lock=threading.RLock()
    def available(self)->bool: return bool(self.cfg.get("enabled",True)) and self.path.is_file()
    def _load(self):
        if self._model is not None:return
        if not self.available(): raise RuntimeError(f"YOLO model not found: {self.path}")
        from ultralytics import YOLO
        self._model=YOLO(str(self.path))
    def _device(self):
        requested = self.cfg.get("device", "auto")
        if str(requested).strip().lower() != "auto":
            return requested
        # Ultralytics does not accept the literal string ``auto`` on every
        # version/backend. Resolve it once using PyTorch so CPU R&D machines
        # and CUDA-capable Linux/Jetson deployments both get a valid value.
        try:
            import torch
            return 0 if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def detect_jpeg(self,jpeg:bytes)->list[dict[str,Any]]:
        with self._lock:
            return self._detect_locked(jpeg)

    def _detect_locked(self, jpeg: bytes) -> list[dict[str, Any]]:
        self._load(); import cv2, numpy as np
        img=cv2.imdecode(np.frombuffer(jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
        if img is None: raise ValueError("Could not decode JPEG")
        results=self._model.predict(img,conf=float(self.cfg.get("confidence",0.35)),device=self._device(),imgsz=int(self.cfg.get("image_size",416)),verbose=False)
        out=[]; limit=int(self.cfg.get("max_detections",30))
        for r in results:
            names=getattr(r,"names",{})
            for b in getattr(r,"boxes",[])[:limit]:
                xyxy=[float(v) for v in b.xyxy[0].tolist()]; cls=int(b.cls[0]); conf=float(b.conf[0])
                out.append({"class_id":cls,"label":str(names.get(cls,cls)),"confidence":conf,"xyxy":xyxy})
        return out

class NullDetector:
    def available(self): return False
    def detect_jpeg(self,jpeg): return []
