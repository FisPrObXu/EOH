"""Build a native-coordinate review editor; annotations are separate from labels."""
import base64
import hashlib
import json
import re
from pathlib import Path
import cv2
import numpy as np
import pandas as pd
from PIL import Image

from app_runtime import ROOT

def runs(mask):
    x = np.r_[False, mask.ravel(), False].astype(np.int8)
    start = np.flatnonzero(np.diff(x) == 1)
    stop = np.flatnonzero(np.diff(x) == -1)
    return np.column_stack([start, stop-start]).tolist()

def paths(mask):
    cs, _ = cv2.findContours(mask.astype('uint8'), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    return [c[:, 0, :].tolist() for c in cs]

def build(out=ROOT, data=None):
    out = Path(out)
    payload = {}
    for i in ['21', '24']:
        if data is None:
            bright = pd.read_csv(out/'tables'/f'{i}_particles.csv')
            gray = pd.read_csv(out/'tables'/f'{i}_inclusions_and_rejected.csv')
            m = {k: np.array(Image.open(out/'masks'/f'{i}_{k}.tif'))
                 for k in ['bright_labels', 'inclusion_labels', 'gray_raw_labels']}
            m.update({k: np.array(Image.open(out/'masks'/f'{i}_{k}.png')) > 0 for k in ['W', 'A']})
            scale = json.loads((ROOT/'config.json').read_text(encoding='utf-8-sig'))['images'][i]['pixel_size_um']
        else:
            bright, gray, m, scale = data[i]['bright'], data[i]['gray'], data[i]['m'], data[i]['s']
        objects = json.loads(pd.concat([bright, gray], ignore_index=True).to_json(orient='records'))
        for row in objects: row['image_id'] = i
        outlines = []
        for row in objects:
            key = {'candidate_bright_particle': 'bright_labels', 'candidate_gray_inclusion': 'inclusion_labels',
                   'gray_component_rejected': 'gray_raw_labels'}[row['object_class']]
            if row['object_class'] == 'gray_component_rejected': continue
            x0, y0, x1, y1 = [int(row[k]) for k in ['bbox_x0', 'bbox_y0', 'bbox_x1', 'bbox_y1']]
            local = paths(m[key][y0:y1, x0:x1] == row['native_label'])
            outlines.append(dict(object_id=row['object_id'], object_class=row['object_class'],
                paths=[[[x+x0, y+y0] for x, y in p] for p in local]))
        native = out/'report'/f'{i}_native_grayscale.png'
        payload[i] = dict(width=1024, height=691, pixel_size_um=scale, objects=objects,
            contours=outlines, window_paths=paths(m['W']), W_runs=runs(m['W']), A_runs=runs(m['A']),
            image='data:image/png;base64,'+base64.b64encode(native.read_bytes()).decode())
    # Bind review decisions to this exact object and window dataset, even after IDs change.
    binding = {i: {k: v for k, v in x.items() if k != 'image'} for i, x in payload.items()}
    dataset_id = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()[:20]
    document = dict(schema_version=1, dataset_id=dataset_id, fields=payload)
    template = (ROOT/'code'/'review_editor.html').read_text(encoding='utf-8')
    html = template.replace('__REVIEW_DATA__', json.dumps(document, ensure_ascii=False).replace('</', '<\\/'))
    (out/'report'/'Object_Review.html').write_text(html, encoding='utf-8')
    (out/'logs'/'review_dataset.json').write_text(json.dumps(dict(dataset_id=dataset_id), indent=2))
    print('Review editor built:', out/'report'/'Object_Review.html')

def refresh_template():
    target=ROOT/'report'/'Object_Review.html'
    existing=target.read_text(encoding='utf-8')
    payload=re.search(r'<script id="review-data" type="application/json">(.*?)</script>',existing,re.S).group(1)
    template=(ROOT/'code'/'review_editor.html').read_text(encoding='utf-8')
    target.write_text(template.replace('__REVIEW_DATA__',payload),encoding='utf-8')
    print('Review interface updated; original embedded dataset and saved annotations preserved.')

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--template-only',action='store_true')
    if parser.parse_args().template_only:refresh_template()
    else:build()
