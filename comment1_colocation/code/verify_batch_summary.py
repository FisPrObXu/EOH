"""Exercise checkbox export, frozen-report synthesis, missing-report recovery, and closing."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from self_service_engine import ROOT,load,dump,tempdir,configure_temp,safe_remove,UserError


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_case(source,destination):
    destination.mkdir(parents=True)
    for name in ['inputs','masks','tables']:shutil.copytree(source/name,destination/name)
    (destination/'report'/'review_annotations').mkdir(parents=True)
    for name in ['Object_Review.html','1_native_grayscale.png']:shutil.copyfile(source/'report'/name,destination/'report'/name)
    shutil.copyfile(source/'report'/'review_annotations'/'review_annotations.json',destination/'report'/'review_annotations'/'review_annotations.json')
    for name in ['case.json','config.json']:shutil.copyfile(source/name,destination/name)
    (destination/'logs').mkdir();(destination/'results').mkdir()


def main():
    import numpy as np
    import pandas as pd
    import fitz
    from batch_summary import build_summary
    from self_service_gui import App
    original_cases=ROOT.parent/'分析结果';watched=[]
    for case in original_cases.iterdir():
        if (case/'case.json').exists():
            watched.extend(p for p in [case/'case.json',case/'config.json',case/'latest_report.json',case/'report'/'review_annotations'/'review_annotations.json'] if p.exists())
    old_hashes={str(p):sha(p) for p in watched};work=tempdir(ROOT/'_tmp','batchcheck');configure_temp(work/'runtime');cases=work/'cases';cases.mkdir()
    result=dict(checks={},temporary_directory=str(work));checks=result['checks'];log=ROOT/'logs'/'batch_summary_validation.json';apps=[]
    try:
        for name in ['batch_summary.py','self_service_gui.py','self_service_engine.py']:ast.parse((ROOT/'code'/name).read_text(encoding='utf-8'))
        checks['python_syntax']=True
        for name in ['1','2','4']:stage_case(original_cases/name,cases/name)
        latest=load(original_cases/'1'/'latest_report.json');old=original_cases/'1'/'results'/latest['run']
        shutil.copytree(old,cases/'1'/'results'/'frozen',ignore=shutil.ignore_patterns('Export.zip'))
        latest.update(run='frozen',report=str(cases/'1'/'results'/'frozen'/'report'/'Report.html'),grain_report=str(cases/'1'/'results'/'frozen'/'report'/'Grain_Size_Report.html'))
        dump(cases/'1'/'latest_report.json',latest);shutil.copyfile(old/'inputs'/'review.json',cases/'1'/'report'/'review_annotations'/'review_annotations.json')
        if (original_cases/'1'/'plot_settings.json').exists():shutil.copyfile(original_cases/'1'/'plot_settings.json',cases/'1'/'plot_settings.json')
        app=App(cases,hidden=True);apps.append(app);app.geometry('1040x820+5000+5000');app.deiconify();app.update()
        box=app.tree.bbox('1','checked');assert box
        app.tree.event_generate('<Button-1>',x=box[0]+box[2]//2,y=box[1]+box[3]//2);app.update();assert app.checked_cases=={'1'}
        app.toggle_check('4');app.refresh();assert app.checked_cases=={'1','4'} and app.tree.set('1','checked')=='☑'
        recorded=[]
        with patch.object(app,'run',side_effect=lambda args:recorded.append((args,load(app.runtime/'summary_selection.json')))):app.summary_button.invoke()
        assert set(recorded[0][1]['cases'])=={'1','4'} and recorded[0][0][0]=='summarize'
        app.check_all(True);assert app.checked_cases=={'1','2','4'};app.check_all(False);assert not app.checked_cases
        with patch('self_service_gui.messagebox.showinfo') as info,patch.object(app,'run') as run:
            app.summary_button.invoke();assert info.called and not run.called
        checks['native_checkbox_click_and_refresh']=True;checks['select_all_clear_and_only_checked_export']=True
        app.close();assert not app.runtime.exists();checks['normal_close_removes_owned_runtime']=True
        app=App(cases,hidden=True);apps.append(app);runtime=app.runtime;marker=(runtime/'.temporary-owner.json').read_bytes();(runtime/'.temporary-owner.json').unlink()
        app.close();assert load(ROOT/'logs'/'desktop_cleanup.json')['temporary_removed'] is False
        (runtime/'.temporary-owner.json').write_bytes(marker);safe_remove(runtime,ROOT/'_tmp');checks['missing_owner_marker_does_not_block_close']=True
        app=App(cases,hidden=True);apps.append(app);runtime=app.runtime
        with patch('self_service_gui.safe_remove',side_effect=PermissionError('simulated locked cache')):app.close()
        assert load(ROOT/'logs'/'desktop_cleanup.json')['temporary_removed'] is False
        safe_remove(runtime,ROOT/'_tmp');checks['cleanup_error_does_not_block_close']=True
        app=App(cases,hidden=True);apps.append(app)
        class FinishedWorker:
            def poll(self):return 0
        app.worker=FinishedWorker();app.close();assert app.closing;checks['finished_worker_does_not_block_close']=True
        interrupted=tempdir(work,'interrupted')
        def fail_after_marker(path):
            (path/'.temporary-owner.json').unlink();raise PermissionError('simulated partial deletion')
        with patch('self_service_engine._remove_owned_tree',side_effect=fail_after_marker):
            try:safe_remove(interrupted,work)
            except PermissionError:pass
        assert (interrupted/'.temporary-owner.json').exists();safe_remove(interrupted,work)
        checks['interrupted_cleanup_preserves_owner_marker']=True
        configure_temp(work/'runtime')
        try:build_summary(dict(cases=[]),cases)
        except UserError:checks['empty_selection_rejected']=True
        else:raise AssertionError('empty selection accepted')
        dump(log,result)
        output=build_summary(dict(cases=['1','4']),cases)
        manifest=load(output/'inputs'/'source_manifest.json');assert [r['name'] for r in manifest['cases']]==['1','4']
        assert set(p.name for p in (output/'sources').iterdir())=={'C01','C02'}
        checks['only_selected_cases_exported']=True
        assert manifest['cases'][0]['human_review_confirmed'] and not manifest['cases'][1]['human_review_confirmed']
        assert not manifest['cases'][1]['spatial_available'] and (cases/'4'/'latest_report.json').exists()
        checks['missing_reports_rebuilt_without_false_review_confirmation']=True
        grain=pd.read_csv(output/'tables'/'all_grain_regions.csv');pooled=pd.read_csv(output/'tables'/'pooled_grain_summary.csv')
        for kind in ['bright','gray']:
            values=grain.loc[(grain.kind==kind)&grain.included,'equivalent_circle_diameter_um']
            summary=pooled.loc[pooled.kind==kind].iloc[0]
            assert len(values)==summary.N and np.isclose(values.mean(),summary.mean_um) and np.isclose(values.median(),summary.median_um)
        checks['pooled_grain_counts_means_medians_exact']=True
        combined=pd.read_csv(output/'tables'/'point_combined_G01.csv');source=pd.read_csv(old/'tables'/'point_curves.csv')
        assert np.allclose(combined.observed,source.observed) and np.allclose(combined.baseline,source.baseline)
        checks['distance_weighting_and_parameter_groups']=True
        spatial=pd.read_csv(output/'tables'/'case_spatial_summary.csv');assert np.isclose(spatial.loc[spatial.code=='C01','curve_p'].iloc[0],load(old/'logs'/'point_summary.json')['curve_p'])
        assert manifest['pooled_inference'] is False;checks['individual_p_values_preserved_no_fabricated_pooled_p']=True
        pdf=load(output/'logs'/'pdf_validation.json');assert len(pdf['source_reports'])==3 and pdf['page_count_matches']
        with fitz.open(output/'Summary.pdf') as doc:
            assert doc.page_count==pdf['pages'] and doc.get_toc()
            assert '所选案例' in doc[0].get_text()
        checks['both_original_reports_appended_and_pdf_pages_verified']=True
        import zipfile
        with zipfile.ZipFile(output/'Export.zip') as archive:
            names=archive.namelist();assert 'Summary.pdf' in names and 'Summary.html' in names and 'inputs/source_manifest.json' in names
            assert any(n.startswith('sources/C01/') for n in names) and any(n.startswith('sources/C02/') for n in names)
            assert not any('_runtime' in n for n in names)
        checks['portable_bundle_includes_selected_reports_inputs_tables']=True
        for figure in load(output/'logs'/'figures.json'):
            stem=figure['stem']
            for ext in ['pdf','svg','png','tiff']:assert (output/'figures'/f'{stem}.{ext}').exists()
            assert not load(output/'logs'/f'{stem}.collision.json')['summary']['fail']
            assert not load(output/'logs'/f'{stem}.text.json')['below_minimum_count']
            shutil.copyfile(output/'logs'/f'{stem}.preview.png',ROOT/'logs'/f'batch_{stem}.preview.png')
        for i in range(1,5):shutil.copyfile(output/'logs'/f'summary_page_{i:02d}.png',ROOT/'logs'/f'batch_summary_page_{i:02d}.png')
        checks['independent_figure_formats_fonts_collisions']=True
        checks['original_cases_unmodified']=all(sha(Path(p))==value for p,value in old_hashes.items());assert checks['original_cases_unmodified']
        result.update(status='passed',selected_cases=['1','4'],summary_pages=pdf['pages'],figure_count=len(load(output/'logs'/'figures.json')))
        dump(log,result)
    except Exception as error:result.update(status='failed',error=str(error));dump(log,result);raise
    finally:
        for app in apps:
            try:
                if app.winfo_exists():app.finish_close()
            except Exception:pass
        configure_temp(ROOT/'_tmp')
        if work.exists():safe_remove(work,ROOT/'_tmp')
        result['test_temporary_removed']=not work.exists();dump(log,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
