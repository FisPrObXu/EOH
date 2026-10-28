"""Verify English application text, preserved computation and small-screen controls."""
import ast
import re
from pathlib import Path
from self_service_engine import ROOT,load,dump,configure_temp

HAN=re.compile('[\u3400-\u9fff]')
STORAGE={'工作数据','操作说明.html','EOH_中文说明手册.html','汇总报告','分析结果','打开最新报告.html','粒径报告.html'}


def main():
    work=Path(load(ROOT/'logs/upgrade_release_work.json')['work']);configure_temp(work/'english_verifier')
    checks={};names=load(ROOT/'logs/portable_build_inputs.json')['modules']
    residual=[]
    for name in names:
        for node in ast.walk(ast.parse((ROOT/'code'/(name+'.py')).read_text('utf-8'))):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and HAN.search(node.value) and node.value not in STORAGE:
                residual.append((name,node.lineno,node.value[:100]))
    assert not residual,residual
    assert not any(HAN.search((ROOT/'code'/name).read_text('utf-8')) for name in ['review_editor.html','review_exclusions.js'])
    checks['all_runtime_text_english_except_existing_storage_names_and_manual_path']=True
    class StripText(ast.NodeTransformer):
        def visit_Constant(self,node):
            if isinstance(node.value,str):node.value='<text>'
            return node
    computation=['acceleration.py','analysis.py','analyze_review21.py','area_redistribution21.py','apply_review21.py','segmentation.py','exclusion_geometry.py','bright_segmentation.py','grain_size_analysis.py','summary_publication.py']
    for name in computation:
        old=StripText().visit(ast.parse((work/'original_code'/name).read_text('utf-8')))
        new=StripText().visit(ast.parse((ROOT/'code'/name).read_text('utf-8')))
        assert ast.dump(old)==ast.dump(new),name
    checks['computation_structure_unchanged_only_text_translated']=True
    from self_service_gui import App,ImportDialog,PlotSettingsDialog,BrightDetectionDialog
    from PIL import Image
    Image.new('L',(256,256),150).save(work/'qa.png');case=work/'ui_case';dump(case/'case.json',dict(name='EOH QA'))
    count=0
    def inspect(widget):
        nonlocal count
        for key in ['text','values']:
            if key in widget.keys():
                value=str(widget.cget(key));assert not HAN.search(value),(str(widget),key,value);count+=1
        for child in widget.winfo_children():inspect(child)
    for scale in [1.,1.5,2.]:
        app=App(work/'ui_cases',hidden=True);app.tk.call('tk','scaling',scale);app.geometry('900x500+5000+5000');app.deiconify();app.update()
        assert app.title()=='EOH — Eyes of heaven | 0.4.1';inspect(app)
        for kind in ['import','plot','summary','bright']:
            form=ImportDialog(app,work/'qa.png',lambda spec:None,hidden=True) if kind=='import' else BrightDetectionDialog(app,case,lambda value:None,hidden=True) if kind=='bright' else PlotSettingsDialog(app,case,hidden=True,on_redraw=(lambda:None) if kind=='summary' else None,scope='summary' if kind=='summary' else 'case')
            form.geometry('760x500+5000+5000');form.deiconify();form.update();inspect(form)
            button=form.accept_button if kind=='import' else form.create_button if kind=='bright' else form.save_button
            assert button.winfo_ismapped(),(scale,kind)
            assert button.winfo_rooty()+button.winfo_height()<=form.winfo_rooty()+form.winfo_height(),(scale,kind,'bottom')
            assert button.winfo_rootx()+button.winfo_width()<=form.winfo_rootx()+form.winfo_width(),(scale,kind,'right')
            form.destroy()
        app.close();configure_temp(work/'english_verifier')
    checks['english_desktop_and_four_dialog_types_at_three_scales']=True
    checks['main_action_buttons_inside_760x500_dialogs']=True
    manual=(ROOT.parent/'EOH_中文说明手册.html').read_text('utf-8')
    assert all(word in manual for word in ['Eyes of heaven','0.4.1','Save all changes','Plot settings','Exclusion radius'])
    checks['separate_chinese_manual_matches_english_controls']=True
    from app_runtime import error_message
    error=PermissionError(13,'Access denied');error.winerror=5
    assert 'Access is denied' in error_message(error),error_message(error)
    checks['windows_file_error_display_uses_english']=True
    from unittest.mock import patch
    from self_service_engine import import_image
    original_case=ROOT.parent/'分析结果/3';meta=load(original_case/'case.json');original=next((original_case/'inputs').glob('original.*'))
    with patch.object(Path,'rename',side_effect=PermissionError(5,'Access denied')):
        imported=import_image(dict(source=str(original),name='EOH QA',crop=meta['crop_xyxy'],pixel_size_um=meta['pixel_size_um'],adaptive_segmentation=True),work/'r')
    assert next((imported/'inputs').glob('original.*')).read_bytes()==original.read_bytes()
    assert load(imported/'case.json')['dataset_id']==load(imported/'report/review_annotations/review_annotations.json')['dataset_id']
    assert not (imported/'.temporary-owner.json').exists()
    checks['import_succeeds_when_windows_denies_directory_rename']=True
    result=dict(status='passed',product='EOH',version='0.4.1',checks=checks,widget_text_checks=count)
    dump(ROOT/'logs/eoh_english_validation.json',result);print(result,flush=True)


if __name__=='__main__':main()
