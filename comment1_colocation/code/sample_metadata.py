"""Explicit case-to-sample declarations; filenames never imply independence."""
from pathlib import Path
from self_service_engine import load


def resolve(records,folder):
    path=Path(folder)/'sample_identity.json'
    if not path.exists():return dict(available=False,reason='Sample identities not supplied.',case_samples={})
    data=load(path);entries=data.get('cases',{});case_samples={};missing=[]
    for r in records:
        entry=entries.get(r['case_id'],{});sample=str(entry.get('sample_id','')).strip()
        if not sample or not r.get('source_sha256') or entry.get('source_sha256')!=r['source_sha256']:
            missing.append(r['name'])
        else:case_samples[r['code']]=sample
    hashes=[r.get('source_sha256') for r in records];selected_hashes=set(hashes);conflicts=[]
    for entry in data.get('overlap_conflicts',[]):
        if set(entry.get('source_sha256',[])).issubset(selected_hashes):conflicts.append(entry)
    if len(hashes)!=len(set(hashes)):
        return dict(available=False,reason='Duplicate source images in selection; sample bootstrap withheld.',case_samples=case_samples,overlap_conflicts=conflicts)
    if missing:return dict(available=False,reason='Sample IDs missing or source identity changed: '+', '.join(missing),case_samples=case_samples,overlap_conflicts=conflicts)
    ids=sorted(set(case_samples.values()))
    if len(ids)<2:return dict(available=False,reason='At least two independent samples are required for a sample bootstrap.',case_samples=case_samples,overlap_conflicts=conflicts)
    return dict(available=True,case_samples=case_samples,sample_ids=ids,independent_sample_count=len(ids),overlap_conflicts=conflicts,
                assumption='Distinct sample IDs identify independent samples; fields sharing an ID are resampled together.',source=str(path),bootstrap_replicates=2000,seed=20261028)
