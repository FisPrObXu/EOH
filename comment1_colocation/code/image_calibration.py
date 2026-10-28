"""Saved calibration for the inspected inputs; never infer physical scale from print DPI."""
import hashlib
from pathlib import Path
from self_service_engine import ROOT,load


def known_calibration(source):
    path=ROOT/'logs'/'new_image_calibration.json'
    if not path.exists():return None
    fingerprint=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    for row in load(path)['images']:
        if row['source_sha256']==fingerprint:return row
    return None
