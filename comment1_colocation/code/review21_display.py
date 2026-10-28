"""Export saved review paths faithfully and audit them against the applied native labels.

Figure contract: a single microscopy plate documents the saved geometry, including
small candidates omitted from quantification. It makes no association claim.
Python/Matplotlib; 89 x 86 mm; editable vectors and 600 dpi raster companions.
"""
import argparse
import copy
import html
import json
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from PIL import Image
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams.update({'pdf.fonttype': 42, 'svg.fonttype': 'none'})
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from apply_review21 import ROOT
from audit_panel_alignment import require_matplotlib_panel_alignment
from publication21_figures import style

COLORS = dict(gray='#2878b5', bright='#aa3377', manual='#19a098', window='#d88216')


def saved_model(review_path, image_id='21',project_root=None):
    image_id=str(image_id)
    root=Path(project_root) if project_root is not None else ROOT
    review = json.loads(Path(review_path).read_text(encoding='utf-8'))
    page = (root/'report'/'Object_Review.html').read_text(encoding='utf-8')
    base = json.loads(re.search(r'<script id="review-data" type="application/json">(.*?)</script>', page, re.S).group(1))
    if review['dataset_id'] != base['dataset_id']:
        raise ValueError('Saved review belongs to another image dataset')
    field = base['fields'][image_id]
    objects = {r['object_id']: dict(copy.deepcopy(r), paths=[], manual=False, operations=[], decision=None)
               for r in field['objects']}
    for c in field['contours']:
        objects[c['object_id']]['paths'] = copy.deepcopy(c['paths'])
    active = set(review['active_ids'])
    edits = [a for a in review['actions'] if a['id'] in active and a['image_id'] == image_id]
    for a in edits:
        oid, op = a['object_id'], a['operation']
        if op in ['add_exclusion','replace_exclusion','delete_exclusion']:continue
        if op == 'add_outline':
            objects[oid] = dict(object_id=oid, object_class=a['object_class'], paths=[a['points']],
                                native_label=None, manual=True, operations=[], decision=None)
        r = objects[oid]
        if op in ('replace_outline', 'delete_outline'):
            k = a.get('path_index', 0)
            while len(r['paths']) <= k:
                r['paths'].append(None)
            r['paths'][k] = a['points'] if op == 'replace_outline' else None
            if op == 'replace_outline':
                r['manual'] = True
                r['object_class'] = a['object_class']
        if op in ('keep', 'exclude', 'uncertain'):
            r['decision'] = op
        r['operations'].append(op)
    if image_id=='1' and (root/'masks'/'1_base_A.png').exists():
        from exclusion_geometry import update_field_context
        field=update_field_context(root,field,review)
    return review, field, objects, edits


def plot_paths(ax, field, objects):
    """Keep saved geometry; encode reviewed object class, regardless of edit history."""
    drawn = []
    for path in field['window_paths']:
        p = np.asarray(path, dtype=float) + .5
        if len(p) > 2:
            p = np.vstack([p, p[0]])
        ax.plot(p[:, 0], p[:, 1], color=COLORS['window'], lw=.5, ls=(0, (4, 2.7)))
    for oid, r in objects.items():
        if r['object_class'] == 'gray_component_rejected':
            continue
        kind = 'bright' if r['object_class'] == 'candidate_bright_particle' else 'gray'
        color = COLORS[kind]
        for k, path in enumerate(r['paths']):
            # A one-vertex canvas stroke has no visible length; preserve that behaviour.
            if not path or len(path) < 2:
                continue
            p = np.asarray(path, dtype=float) + .5
            if len(p) > 2:
                p = np.vstack([p, p[0]])
            ax.plot(p[:, 0], p[:, 1], color=color, lw=.45,
                    ls=(0, (3, 3)) if r['decision'] == 'exclude' else '-',
                    solid_capstyle='butt', solid_joinstyle='round')
            drawn.append(dict(object_id=oid, path_index=k, vertices=path, color=color))
    return drawn


def draw_review(out, review_path, stem='02_Reviewed_Contours', image_id='21'):
    image_id=str(image_id)
    review, field, objects, _ = saved_model(review_path,image_id)
    scale=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['images'][image_id]['pixel_size_um']
    fig, ax = plt.subplots(figsize=(3.5039370079, 3.3858267717))
    fig.subplots_adjust(left=.04, right=.98, bottom=.19, top=.90)
    gray = np.array(Image.open(ROOT/'report'/f'{image_id}_native_grayscale.png'))
    ax.imshow(gray, cmap='gray', vmin=0, vmax=255, interpolation='none')
    ax.set_xlim(-.5, 1023.5)
    ax.set_ylim(800, -.5)
    ax.set_axis_off()
    ax.set_title('Reviewed bright and dark regions', pad=8)
    drawn = plot_paths(ax, field, objects)
    ax.plot([55, 55+10/scale], [750, 750], color='black', lw=1.8)
    ax.text(75+10/scale, 750, '10 μm', va='center', fontsize=7)
    legend = [Line2D([], [], color=COLORS[c], lw=.8, ls='--' if c == 'window' else '-', label=label)
              for c, label in [('gray', 'Dark regions'), ('bright', 'Bright regions'),
                               ('window', 'Protected window W')]]
    fig.legend(handles=legend, loc='lower center', bbox_to_anchor=(.5, .015), ncol=2,
               columnspacing=.8, handlelength=1.6)
    require_matplotlib_panel_alignment(fig, json_out=out/'logs'/f'{stem}.alignment.json', strict=True)
    fig.savefig(out/'figures'/f'{stem}.pdf', dpi=600)
    fig.savefig(out/'figures'/f'{stem}.svg', dpi=600)
    fig.savefig(out/'figures'/f'{stem}.png', dpi=600)
    with Image.open(out/'figures'/f'{stem}.png') as im:
        im.convert('RGB').save(out/'figures'/f'{stem}.tiff', compression='tiff_lzw', dpi=(600, 600))
    plt.close(fig)
    (out/'logs'/'review_drawn_paths.json').write_text(json.dumps(dict(
        revision=review['revision'], selected_object_highlight=False, paths=drawn,
        color_encoding='reviewed object class',
        note='All normally displayed saved paths; no minimum-size or W filter applied to this drawing.'),
        ensure_ascii=False, indent=2), encoding='utf-8')


def audit_review(out, review_path, reviewed):
    review, field, objects, edits = saved_model(review_path)
    applied = json.loads((reviewed/'logs'/'review_used.json').read_text(encoding='utf-8'))
    if any(review[k] != applied[k] for k in ['dataset_id', 'actions', 'active_ids']):
        raise ValueError('Saved geometry differs from applied analysis; apply and recompute before export')
    table = pd.read_csv(reviewed/'tables'/'reviewed_objects.csv').set_index('object_id')
    mapping = pd.read_csv(reviewed/'tables'/'reviewed_label_mapping.csv').set_index('object_id')
    A = np.array(Image.open(reviewed/'masks'/'21_A.png')) > 0
    native = {k: np.array(Image.open(ROOT/'masks'/f'21_{s}.tif'))
              for k, s in [('gray', 'inclusion_labels'), ('bright', 'bright_labels')]}
    labels = {k: np.array(Image.open(reviewed/'masks'/f'21_{s}.tif'))
              for k, s in [('gray', 'inclusion_labels'), ('bright', 'bright_labels')]}
    reasons = {'below_auto_minimum': 'Below original automatic area threshold: displayed, excluded from statistics',
               'deleted_outline': 'Outline deleted', 'outside_protected_W': 'Outline applied; center outside W, excluded from main statistics',
               'user_excluded': 'Manually excluded'}
    rows = []
    for oid, r in objects.items():
        if oid not in table.index:
            continue
        t = table.loc[oid]
        kind = t.kind
        changed = bool(r['manual'] or 'delete_outline' in r['operations'])
        if changed:
            expected = np.zeros(A.shape, np.uint8)
            polygons = [np.rint(np.asarray(p)*256).astype(np.int32)[:, None, :]
                        for p in r['paths'] if p and len(p) >= 3]
            if polygons:
                cv2.fillPoly(expected, polygons, 1, shift=8)
            expected = expected > 0
        else:
            expected = native[kind] == int(r['native_label'])
        if kind == 'gray':
            expected &= A
        if not t.eligible:
            expected[:] = False
        actual = labels[kind] == int(mapping.loc[oid, 'reviewed_native_label']) if oid in mapping.index else np.zeros(A.shape, bool)
        matches = np.array_equal(expected, actual)
        if not matches:
            raise AssertionError(f'Applied native geometry differs for {oid}')
        reason = str(t.exclusion_reason) if pd.notna(t.exclusion_reason) else ''
        explanation = reasons.get(reason, 'Gray region used as a distance target' if kind == 'gray' else 'Included in bright-object distance statistics')
        rows.append(dict(object_id=oid, kind=kind, manual_geometry=changed,
                         active_operation_count=len(r['operations']), operations=' / '.join(r['operations']),
                         browser_contour_present=any(bool(p) for p in r['paths']),
                         export_contour_present=any(bool(p) and len(p) >= 2 for p in r['paths']),
                         eligible=bool(t.eligible), in_W=bool(t.in_W), in_bright_statistics=bool(kind == 'bright' and t.included),
                         used_as_gray_target=bool(kind == 'gray' and t.eligible and actual.any()),
                         retained_native_pixels=int(actual.sum()), pixel_geometry_matches=matches,
                         reason_code=reason, explanation_zh=explanation))
    frame = pd.DataFrame(rows)
    frame.to_csv(out/'report'/'All_Objects_Review_Audit.csv', index=False, encoding='utf-8-sig')
    action_rows = []
    active = set(review['active_ids'])
    for a in review['actions']:
        if a['image_id'] != '21':
            continue
        oid = a['object_id']
        row = frame.loc[frame.object_id == oid]
        final = row.iloc[0] if len(row) else None
        action_rows.append(dict(action_id=a['id'], object_id=oid, operation=a['operation'],
                                active=a['id'] in active,
                                final_pixel_geometry_matches=bool(final.pixel_geometry_matches) if final is not None else None,
                                explanation_zh='Active actions applied in order; last redraw used per outline' if a['id'] in active else 'Undone action; not applied'))
    pd.DataFrame(action_rows).to_csv(out/'report'/'All_Review_Actions_Audit.csv', index=False, encoding='utf-8-sig')
    summary = dict(review_revision=review['revision'], active_operation_counts=dict(Counter(a['operation'] for a in edits)),
                   audited_objects=len(frame), all_objects_pixel_geometry_matches=bool(frame.pixel_geometry_matches.all()),
                   manual_objects_checked=int(frame.manual_geometry.sum()),
                   originally_filtered_small_bright=frame.loc[frame.reason_code == 'below_auto_minimum', 'object_id'].tolist(),
                   retained_bright=int(((frame.kind == 'bright') & frame.eligible).sum()),
                   bright_in_statistics=int(frame.in_bright_statistics.sum()),
                   bright_outside_W=int((frame.reason_code == 'outside_protected_W').sum()),
                   color_encoding='reviewed bright/dark class', analysis_masks_changed=False)
    (out/'logs'/'review_display_audit.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    columns = ['object_id', 'kind', 'operations', 'retained_native_pixels', 'explanation_zh']
    body = f'<h1>21: outline display and application audit</h1><p>Saved revision {review["revision"]}. Outlines use class colors: magenta for bright and blue for dark, including original, added and redrawn objects. Small candidates remain visible regardless of statistical thresholds. Yellow marks the current browser selection, not saved geometry.</p>'
    counts = Counter(a['operation'] for a in edits)
    body += f'<p>Checked all {len(edits)} active actions: {counts["add_outline"]} additions, {counts["replace_outline"]} redraws, {counts["delete_outline"]} deletions and {counts["keep"]} Keep decisions. {len(frame)} objects match their final native-pixel geometry.</p>'
    body += f'<p>Figures and browser use the same saved paths and class colors. {len(summary["originally_filtered_small_bright"])} candidates below the original automatic area threshold remain visible. Single-vertex paths have no visible line length, as in the browser. The area threshold and W are unchanged in this display correction. Of {summary["retained_bright"]} retained bright objects, {summary["bright_in_statistics"]} lie inside W and enter statistics; {summary["bright_outside_W"]} lie outside W.</p>'
    body += '<p><a href="All_Objects_Review_Audit.csv">All-object audit CSV</a> · <a href="All_Review_Actions_Audit.csv">All-action audit CSV</a> · <a href="Single_Figures_Index.html">Separate figures</a></p>'
    body += f'<img src="../figures/02_Reviewed_Contours.png?review={review["revision"]}&amp;display=paths" style="width:100%;max-width:900px" alt="Complete saved review outlines"><p>Filter object ID or reason: <input id="filter" placeholder="e.g. MC0001, MB0010, threshold, outside W" style="width:360px"></p><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in ['Object', 'Class', 'Active edits', 'Retained pixels', 'Application'])+'</tr></thead><tbody>'
    for _, r in frame.iterrows():
        body += '<tr>'+''.join('<td>'+html.escape(str(r[c]))+'</td>' for c in columns)+'</tr>'
    body += '</tbody></table><script>document.getElementById("filter").oninput=e=>{const q=e.target.value.toLowerCase();document.querySelectorAll("tbody tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q));};</script>'
    (out/'report'/'Review_Outline_Audit.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>21 complete outline audit</title><style>body{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1100px;margin:35px auto;padding:20px;line-height:1.7;color:#243342}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #ccd6df;padding:7px;text-align:left}th{background:#eef3f7}input{padding:8px}a{color:#226bb0}</style>'+body+'</html>', encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'_tmp'/'review_display21_stage')
    args = parser.parse_args()
    for folder in ['figures', 'logs', 'report']:
        (args.output/folder).mkdir(parents=True, exist_ok=True)
    source = ROOT/'single_figures21'/'reviewed'
    review = ROOT/'report'/'review_annotations'/'review_annotations.json'
    summary = audit_review(args.output, review, source)
    style()
    draw_review(args.output, review)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
