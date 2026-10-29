"""Native desktop entry point; original images and old reports are never overwritten."""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from urllib.request import urlopen,Request
import webbrowser

from self_service_engine import ROOT,CASES,load,dump,tempdir,safe_remove,configure_temp,validate_spec,validate_output_root,UserError
from plot_settings import read_settings,validate_settings,reference_style,SERIES_NAMES
from responsive_ui import ScrollPanel,fit_window
from app_runtime import command as process_command,FROZEN,error_message

HIDDEN=getattr(subprocess,'CREATE_NO_WINDOW',0)
BRIGHT_SENSITIVITY={'Balanced (recommended)':'balanced','Sensitive (include faint small grains)':'sensitive','Conservative (fewer false positives)':'strict'}
BRIGHT_BOUNDARY={'Standard boundary (recommended)':.35,'Tighter boundary':.5,'Wider boundary':.25}


class BrightDetectionDialog(tk.Toplevel):
    def __init__(self,parent,case,callback,hidden=False):
        super().__init__(parent)
        if hidden:self.withdraw()
        self.title('Enhance bright-grain detection');fit_window(self,650,460);self.callback=callback
        footer=ttk.Frame(self,padding=10);footer.pack(side='bottom',fill='x')
        self.scroll=ScrollPanel(self,padding=20);self.scroll.pack(fill='both',expand=True);frame=self.scroll.body
        ttk.Label(frame,text='Current case: '+load(Path(case)/'case.json')['name'],font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Click Save all changes on the review page first. Enhancement creates a new case and keeps saved manual outlines, deletion decisions and exclusions. Review the new candidates.',wraplength=610).pack(anchor='w',pady=10)
        self.sensitivity=tk.StringVar(value=next(iter(BRIGHT_SENSITIVITY)));self.boundary=tk.StringVar(value=next(iter(BRIGHT_BOUNDARY)));self.minimum=tk.StringVar(value='2')
        for label,var,values in [('Sensitivity',self.sensitivity,BRIGHT_SENSITIVITY),('Boundary extent',self.boundary,BRIGHT_BOUNDARY)]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=7);ttk.Label(row,text=label,width=16).pack(side='left');ttk.Combobox(row,textvariable=var,values=list(values),state='readonly',width=36).pack(side='left')
        row=ttk.Frame(frame);row.pack(fill='x',pady=7);ttk.Label(row,text='Minimum native pixels',width=16).pack(side='left');ttk.Spinbox(row,textvariable=self.minimum,from_=1,to=100,width=10).pack(side='left')
        ttk.Label(frame,text='Higher sensitivity may add noise; wider boundaries increase segmented area. Defaults: balanced, standard boundary, 2 pixels.',wraplength=610).pack(anchor='w',pady=8)
        self.create_button=ttk.Button(footer,text='Save enhanced copy',command=self.accept);self.create_button.pack(side='right')
        self.transient(parent)
        if not hidden:self.grab_set()
    def value(self):
        count=int(self.minimum.get())
        if not 1<=count<=100:raise ValueError('Minimum pixel count must be 1–100.')
        return dict(sensitivity=BRIGHT_SENSITIVITY[self.sensitivity.get()],boundary_fraction=BRIGHT_BOUNDARY[self.boundary.get()],minimum_pixels=count)
    def accept(self):
        try:options=self.value()
        except ValueError as error:messagebox.showerror('Check parameters',error_message(error),parent=self);return
        self.grab_release();self.destroy();self.callback(options)


class ImportDialog(tk.Toplevel):
    def __init__(self,parent,source,callback,hidden=False):
        from PIL import Image,ImageTk
        super().__init__(parent)
        if hidden:self.withdraw()
        self.title('New analysis · Scale and analysis region');fit_window(self,1060,900)
        self.callback=callback;self.source=Path(source);self.result=None
        with Image.open(source) as im:
            if getattr(im,'n_frames',1)!=1 or im.mode not in ['L','P','RGB','RGBA']:
                self.destroy();raise ValueError('Select a single-frame 8-bit BSE image. Export 16-bit images to 8-bit using a known intensity mapping first.')
            self.image=im.convert('L');self.size=im.size
        self.mode=tk.StringVar(value='crop');self.exclusions=[];self.ruler=None;self.start=None
        self.name=tk.StringVar(value=self.source.stem);self.scale=tk.StringVar();self.known=tk.StringVar(value='10')
        self.crop=[tk.StringVar(value=str(v)) for v in [0,0,*self.size]]
        from image_calibration import known_calibration
        self.saved_calibration=known_calibration(source)
        if self.saved_calibration:
            self.scale.set(str(self.saved_calibration['pixel_size_um']))
            for variable,value in zip(self.crop,self.saved_calibration['crop']):variable.set(str(value))
        self.auto=tk.BooleanVar(value=True);self.finite=tk.BooleanVar(value=True);self.adaptive=tk.BooleanVar(value=True);self.analysis_mode=tk.StringVar(value='full');self.values={}
        footer=ttk.Frame(self,padding=8);footer.pack(side='bottom',fill='x')
        self.scroll=ScrollPanel(self,padding=12);self.scroll.pack(fill='both',expand=True);frame=self.scroll.body
        ttk.Label(frame,text='Crop out text and scale-bar panels, then calibrate. Drag to draw a crop or scale bar; coordinates use native pixels.').pack(anchor='w')
        toolbar=ttk.Frame(frame);toolbar.pack(fill='x',pady=6)
        for label,value in [('1. Crop','crop'),('2. Draw scale bar','ruler'),('3. Exclude rectangle','exclude')]:
            ttk.Radiobutton(toolbar,text=label,variable=self.mode,value=value).pack(side='left',padx=5)
        ttk.Button(toolbar,text='Full-image crop',command=self.reset_crop).pack(side='left',padx=6)
        ttk.Button(toolbar,text='Clear rectangles',command=self.clear_exclusions).pack(side='left')
        self.canvas=tk.Canvas(frame,width=1000,height=350,background='#24313d',highlightthickness=0);self.canvas.pack(fill='x')
        self.factor=min(1000/self.size[0],350/self.size[1]);dw,dh=[round(v*self.factor) for v in self.size]
        self.offset=((1000-dw)/2,(350-dh)/2)
        self.photo=ImageTk.PhotoImage(self.image.resize((dw,dh),Image.Resampling.NEAREST),master=self)
        self.canvas.create_image(*self.offset,image=self.photo,anchor='nw')
        self.canvas.bind('<ButtonPress-1>',self.begin);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.end)
        self.hint=tk.StringVar(value=f'Original: {self.size[0]} × {self.size[1]} pixels; the green rectangle marks the retained region.')
        ttk.Label(frame,textvariable=self.hint).pack(anchor='w',pady=3)
        book=ttk.Notebook(frame);book.pack(fill='both',expand=True,pady=5)
        basic=ttk.Frame(book,padding=10);advanced=ttk.Frame(book,padding=10);book.add(basic,text='Required: scale and crop');book.add(advanced,text='Analysis parameters (set before viewing results)')
        ttk.Label(basic,text='Case name').grid(row=0,column=0,sticky='w');ttk.Entry(basic,textvariable=self.name,width=45).grid(row=0,column=1,columnspan=5,sticky='w',pady=3)
        ttk.Label(basic,text='Crop: left / top / right / bottom').grid(row=1,column=0,sticky='w')
        for k,var in enumerate(self.crop):ttk.Entry(basic,textvariable=var,width=9).grid(row=1,column=k+1,padx=3)
        ttk.Button(basic,text='Update preview',command=self.draw_shapes).grid(row=1,column=5,padx=5)
        ttk.Label(basic,text='Scale-bar length (μm)').grid(row=2,column=0,sticky='w',pady=4)
        ttk.Entry(basic,textvariable=self.known,width=12).grid(row=2,column=1,sticky='w');ttk.Button(basic,text='Calibrate from drawn bar',command=self.calibrate).grid(row=2,column=2,columnspan=2)
        ttk.Label(basic,text='Native pixel size (μm/pixel)').grid(row=3,column=0,sticky='w')
        ttk.Entry(basic,textvariable=self.scale,width=20).grid(row=3,column=1,columnspan=2,sticky='w')
        ttk.Label(basic,text='Or enter the physical size of one pixel.').grid(row=3,column=3,columnspan=3,sticky='w')
        ttk.Checkbutton(basic,text='Detect voids / unreadable regions automatically; also apply drawn exclusion rectangles',variable=self.auto).grid(row=4,column=0,columnspan=6,sticky='w',pady=6)
        ttk.Label(basic,text='Edit hole points, crack lines and exclusion radii on the review page next.').grid(row=5,column=0,columnspan=6,sticky='w')
        from bright_segmentation import defaults as bright_defaults
        defaults=dict(load(ROOT/'config.json')['segmentation'],**bright_defaults())
        fields=[('Distance limit (μm)','rmax_um','5'),('Distance step (μm)','step_um','0.25'),('Near-distance threshold (μm)','near_um','1'),('Grain-size edge guard (μm)','size_guard_um','1'),
                ('Legacy bright threshold','bright_threshold',str(defaults['bright_threshold'])),('Bright: minimum pixels','bright_min_pixels',str(defaults['bright_min_pixels'])),
                ('Bright: minimum area (μm²)','bright_min_area_um2',str(defaults['bright_min_area_um2'])),('Dark: residual threshold','gray_residual',str(defaults['gray_residual'])),
                ('Dark: minimum area (μm²)','gray_min_area_um2',str(defaults['gray_min_area_um2'])),('Control count (blank = observed count)','control_count','')]
        for k,(label,key,value) in enumerate(fields):
            row,col=k//3,(k%3)*2;var=tk.StringVar(value=value);self.values[key]=var
            ttk.Label(advanced,text=label).grid(row=row*2,column=col,columnspan=2,sticky='w',padx=8,pady=(3,0))
            ttk.Entry(advanced,textvariable=var,width=23).grid(row=row*2+1,column=col,columnspan=2,sticky='w',padx=8)
        ttk.Checkbutton(advanced,text='Add equal-area controls: preserve total area and count; each region ≤75% of the observed maximum, when feasible',variable=self.finite).grid(row=8,column=0,columnspan=6,sticky='w',pady=7)
        ttk.Checkbutton(advanced,text='Adapt dark-region / void thresholds to image background (review still required)',variable=self.adaptive).grid(row=9,column=0,columnspan=6,sticky='w')
        ttk.Radiobutton(advanced,text='Distance tests + grain sizes',variable=self.analysis_mode,value='full').grid(row=10,column=0,columnspan=3,sticky='w')
        ttk.Radiobutton(advanced,text='Grain sizes only',variable=self.analysis_mode,value='sizes').grid(row=10,column=3,columnspan=3,sticky='w')
        self.bright_enhanced=tk.BooleanVar(value=True);self.bright_sensitivity=tk.StringVar(value=next(iter(BRIGHT_SENSITIVITY)));self.bright_boundary=tk.StringVar(value=next(iter(BRIGHT_BOUNDARY)))
        ttk.Checkbutton(advanced,text='Enhance bright grains: detect small grains by local contrast and expand to their boundaries',variable=self.bright_enhanced).grid(row=11,column=0,columnspan=6,sticky='w',pady=6)
        ttk.Combobox(advanced,textvariable=self.bright_sensitivity,values=list(BRIGHT_SENSITIVITY),state='readonly',width=32).grid(row=12,column=0,columnspan=3,sticky='w')
        ttk.Combobox(advanced,textvariable=self.bright_boundary,values=list(BRIGHT_BOUNDARY),state='readonly',width=28).grid(row=12,column=3,columnspan=3,sticky='w')
        ttk.Label(footer,text='Parameters are saved per case. Create a new case to change scale or crop.',wraplength=350).pack(side='left')
        self.accept_button=ttk.Button(footer,text='Create candidate outlines',command=self.accept);self.accept_button.pack(side='right',padx=8)
        self.draw_shapes();self.transient(parent)
        if not hidden:self.grab_set()

    def native(self,event):
        return tuple(min(self.size[k],max(0,(getattr(event,'xy'[k])-self.offset[k])/self.factor)) for k in range(2))
    def begin(self,event):self.start=self.native(event)
    def motion(self,event):
        if self.start is None:return
        self.draw_shapes();end=self.native(event);pts=[self.offset[k%2]+v*self.factor for k,v in enumerate([*self.start,*end])]
        if self.mode.get()=='ruler':self.canvas.create_line(*pts,fill='#ffff00',width=2,tags='shapes')
        else:self.canvas.create_rectangle(*pts,outline='#ffcf33',width=2,tags='shapes')
    def end(self,event):
        if self.start is None:return
        end=self.native(event);start=self.start;self.start=None
        if math.dist(start,end)<2:return
        if self.mode.get()=='ruler':self.ruler=[list(start),list(end)];self.calibrate()
        else:
            rect=[math.floor(min(start[0],end[0])),math.floor(min(start[1],end[1])),math.ceil(max(start[0],end[0])),math.ceil(max(start[1],end[1]))]
            if self.mode.get()=='crop':
                for var,v in zip(self.crop,rect):var.set(str(v))
            else:self.exclusions.append(rect)
        self.draw_shapes()
    def reset_crop(self):
        for var,v in zip(self.crop,[0,0,*self.size]):var.set(str(v))
        self.draw_shapes()
    def clear_exclusions(self):self.exclusions=[];self.draw_shapes()
    def draw_shapes(self):
        self.canvas.delete('shapes')
        try:
            rect=[int(v.get()) for v in self.crop]
            for r,color in [(rect,'#3ae89d')]+[(r,'#ff5555') for r in self.exclusions]:
                pts=[self.offset[k%2]+v*self.factor for k,v in enumerate(r)];self.canvas.create_rectangle(*pts,outline=color,width=2,tags='shapes')
            if self.ruler:self.canvas.create_line(*[self.offset[k%2]+v*self.factor for k,v in enumerate(sum(self.ruler,[]))],fill='#ffff00',width=2,tags='shapes')
        except ValueError:pass
    def calibrate(self):
        if not self.ruler:self.hint.set('Select Draw scale bar, then drag from one end of the bar to the other.');return
        try:
            known=float(self.known.get());pixels=math.dist(*self.ruler)
            if not math.isfinite(known) or known<=0:raise ValueError()
            self.scale.set(f'{known/pixels:.10g}');self.hint.set(f'Scale bar: {pixels:.3f} native pixels; {known:g} μm ÷ {pixels:.3f} = {known/pixels:.8g} μm/pixel.')
        except ValueError:self.hint.set('The scale-bar length must be positive, in μm.')
    def spec(self):
        a={k:float(self.values[k].get()) for k in ['rmax_um','step_um','near_um','size_guard_um']};a.update(finite=self.finite.get(),control_count=self.values['control_count'].get().strip(),mode=self.analysis_mode.get(),exclusive_phases=True)
        p={k:float(self.values[k].get()) for k in ['bright_threshold','bright_min_area_um2','gray_residual','gray_min_area_um2']};p['bright_min_pixels']=int(self.values['bright_min_pixels'].get())
        from bright_segmentation import defaults as bright_defaults
        p={**bright_defaults(BRIGHT_SENSITIVITY[self.bright_sensitivity.get()],BRIGHT_BOUNDARY[self.bright_boundary.get()]),**p}
        if not self.bright_enhanced.get():p['bright_detection_mode']='threshold'
        spec=dict(source=str(self.source),name=self.name.get().strip() or self.source.stem,pixel_size_um=float(self.scale.get()),crop=[int(v.get()) for v in self.crop],
            auto_domain=self.auto.get(),exclusions=self.exclusions,analysis=a,segmentation=p,adaptive_segmentation=self.adaptive.get(),
            calibration=dict(method='drawn_scale_bar' if self.ruler else 'saved_calibration' if self.saved_calibration else 'manual_pixel_size',line_xy=self.ruler,known_length_um=float(self.known.get()) if self.ruler else None,saved_source=self.saved_calibration))
        validate_spec(spec,self.size);return spec
    def accept(self):
        try:spec=self.spec()
        except (ValueError,KeyError,OverflowError) as e:messagebox.showerror('Check input','Enter a valid scale and parameters.\n'+error_message(e),parent=self);return
        except RuntimeError as e:messagebox.showerror('Check input',error_message(e),parent=self);return
        self.result=spec;self.grab_release();self.destroy();self.callback(spec)


class SettingsTab(ScrollPanel):
    def __init__(self,parent):
        super().__init__(parent,padding=12)


class PlotSettingsDialog(tk.Toplevel):
    MODES={'Automatic bins':'auto','Bin count':'count','Bin width (μm)':'width'}
    STYLES={'Step (empirical cumulative fraction)':'step','Linear connection (display only)':'line','Smooth connection (display only)':'smooth'}

    POSITIONS={'Use template':'template','Reserved space on right':'right','Reserved space below':'below','Inside: upper right':'upper right','Inside: upper left':'upper left','Inside: lower right':'lower right','Inside: lower left':'lower left','Custom coordinates':'custom','Hide legend':'none'}
    LINES={'Template':'auto','Solid':'-','Dashed':'--','Dash-dot':'-.','Dotted':':'}

    def __init__(self,parent,case,on_saved=None,hidden=False,initial_settings=None,on_redraw=None,scope='case'):
        super().__init__(parent)
        if hidden:self.withdraw()
        self.case=Path(case);self.on_saved=on_saved;self.on_redraw=on_redraw;self.enums={};self.series_variables={}
        self.title('Summary plot settings' if scope=='summary' else 'Case plot settings · Saved review retained');fit_window(self,1020,820)
        settings=validate_settings(initial_settings) if initial_settings is not None else read_settings(self.case)
        frame=ttk.Frame(self,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Save and redraw to apply display changes. Numerical data and test parameters stay unchanged.',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=(0,6))
        ttk.Label(frame,text='Canvas and layout settings apply to statistical plots. Original and outline images retain native aspect ratio and scale. Each report saves its plot settings.',wraplength=960).pack(anchor='w')
        scope_text=('These settings control summary plots. Included case reports use their own saved Plot settings. Redraw latest summary also updates the included case figures.' if scope=='summary' else
                    'Current case: '+load(self.case/'case.json').get('name',self.case.name)+'. These settings control this case and are also used in batch summaries and redraws.' if (self.case/'case.json').exists() else
                    'These settings control this case and are also used in batch summaries and redraws.')
        ttk.Label(frame,text=scope_text,wraplength=960).pack(anchor='w',pady=(4,0))
        buttons=ttk.Frame(frame);buttons.pack(side='bottom',fill='x',pady=(12,0))
        ttk.Button(buttons,text='Cancel',command=self.destroy).pack(side='right',padx=8)
        if on_redraw:ttk.Button(buttons,text='Save and redraw latest summary',command=lambda:self.accept(True)).pack(side='right',padx=8)
        self.save_button=ttk.Button(buttons,text='Save plot settings',command=self.accept);self.save_button.pack(side='right')
        ttk.Button(buttons,text='Reset plot defaults',command=self.reset_defaults).pack(side='left')
        ttk.Button(buttons,text='Apply reference style',command=self.apply_reference_style).pack(side='left',padx=8)
        self.book=ttk.Notebook(frame);self.book.pack(fill='both',expand=True,pady=10)
        tabs=[SettingsTab(self.book) for _ in range(3)]
        for tab,title in zip(tabs,['Distributions and curves','Canvas and legend','Plotted objects']):self.book.add(tab,text=title)
        content=tabs[0].body
        box=ttk.LabelFrame(content,text='Grain-size histograms',padding=10);box.pack(fill='x',pady=10)
        self.mode=tk.StringVar(value=next(k for k,v in self.MODES.items() if v==settings['histogram_mode']))
        ttk.Label(box,text='Binning').grid(row=0,column=0,sticky='w',padx=6,pady=5)
        choice=ttk.Combobox(box,textvariable=self.mode,values=list(self.MODES),state='readonly',width=23);choice.grid(row=0,column=1,columnspan=2,sticky='w');choice.bind('<<ComboboxSelected>>',lambda e:self.enable_fields())
        ttk.Label(box,text='Gold (bright)').grid(row=1,column=1,padx=12);ttk.Label(box,text='Chalcopyrite (dark gray)').grid(row=1,column=2,padx=12)
        self.variables={};self.bin_entries={}
        for row,label,keys in [(2,'Number of bins',('bright_bins','gray_bins')),(3,'Bin width (μm)',('bright_bin_width_um','gray_bin_width_um'))]:
            ttk.Label(box,text=label).grid(row=row,column=0,sticky='w',padx=6,pady=5)
            for column,key in enumerate(keys,1):
                var=tk.StringVar(value=str(settings[key]));self.variables[key]=var
                entry=ttk.Entry(box,textvariable=var,width=17);entry.grid(row=row,column=column,padx=12);self.bin_entries[key]=entry
        ttk.Label(box,text='Bar width fraction (0.1–1)').grid(row=4,column=0,sticky='w',padx=6,pady=5)
        self.variables['bar_width_fraction']=tk.StringVar(value=str(settings['bar_width_fraction']))
        ttk.Entry(box,textvariable=self.variables['bar_width_fraction'],width=17).grid(row=4,column=1,padx=12)
        ttk.Label(box,text='1 = touching bars; 0.8 = 20% gap').grid(row=4,column=2,sticky='w')
        self.density=tk.BooleanVar(value=settings['show_density_curve'])
        ttk.Checkbutton(box,text='Overlay a smooth distribution curve (kernel density estimate)',variable=self.density).grid(row=5,column=0,columnspan=3,sticky='w',pady=7)
        ttk.Label(box,text='Density smoothing factor').grid(row=6,column=0,sticky='w',padx=6)
        self.variables['density_bandwidth_factor']=tk.StringVar(value=str(settings['density_bandwidth_factor']))
        ttk.Entry(box,textvariable=self.variables['density_bandwidth_factor'],width=17).grid(row=6,column=1,padx=12)
        ttk.Label(box,text='Default 1; larger = smoother (0.1–5)').grid(row=6,column=2,sticky='w')
        curves=ttk.LabelFrame(content,text='Distance comparisons / grain-size cumulative curves',padding=10);curves.pack(fill='x',pady=(0,10))
        self.style=tk.StringVar(value=next(k for k,v in self.STYLES.items() if v==settings['curve_style']))
        ttk.Label(curves,text='Curve display').grid(row=0,column=0,sticky='w',padx=6,pady=5)
        ttk.Combobox(curves,textvariable=self.style,values=list(self.STYLES),state='readonly',width=29).grid(row=0,column=1,sticky='w')
        ttk.Label(curves,text='Major x-axis interval count').grid(row=1,column=0,sticky='w',padx=6,pady=5)
        self.variables['x_tick_count']=tk.StringVar(value=str(settings['x_tick_count']))
        ttk.Spinbox(curves,from_=3,to=10,textvariable=self.variables['x_tick_count'],width=10).grid(row=1,column=1,sticky='w')
        ttk.Label(curves,text='Random curves (1–4999)').grid(row=2,column=0,sticky='w',padx=6,pady=5)
        self.variables['random_curve_count']=tk.StringVar(value=str(settings['random_curve_count']))
        ttk.Spinbox(curves,from_=1,to=4999,textvariable=self.variables['random_curve_count'],width=10).grid(row=2,column=1,sticky='w')
        ttk.Label(curves,text='4999 = all; only the first layout is shown.',foreground='#135b81').grid(row=3,column=0,columnspan=2,sticky='w',padx=6)
        ttk.Label(content,text='Larger bins give wider bars and fewer bins. Bar width fraction adjusts the gaps. Smooth curves connect saved measurements; tests use the original grid.',wraplength=900,foreground='#135b81').pack(anchor='w')
        layout=tabs[1].body
        def entry(parent,row,label,key,column=0,width=13):
            ttk.Label(parent,text=label).grid(row=row,column=column,sticky='w',padx=7,pady=7)
            variable=tk.StringVar(value=str(settings[key]));self.variables[key]=variable
            ttk.Entry(parent,textvariable=variable,width=width).grid(row=row,column=column+1,sticky='w',padx=7)
        def enum(parent,row,label,key,mapping,column=0,width=19):
            variable=tk.StringVar(value=next(k for k,v in mapping.items() if v==settings[key]));self.enums[key]=(variable,mapping)
            ttk.Label(parent,text=label).grid(row=row,column=column,sticky='w',padx=7,pady=7)
            ttk.Combobox(parent,textvariable=variable,values=list(mapping),state='readonly',width=width).grid(row=row,column=column+1,sticky='w',padx=7)
        canvas=ttk.LabelFrame(layout,text='Canvas and plotting area',padding=10);canvas.pack(fill='x',pady=8)
        entry(canvas,0,'Width, mm (0 = template)','figure_width_mm');entry(canvas,0,'Height, mm (0 = template)','figure_height_mm',2)
        entry(canvas,1,'Axis text, pt (0 = template)','axis_font_size_pt')
        enum(canvas,1,'Grid','grid_mode',{'Use template':'template','Show':'show','Hide':'hide'},2)
        self.custom_margins=tk.BooleanVar(value=settings['custom_margins']);ttk.Checkbutton(canvas,text='Custom margins (% of canvas)',variable=self.custom_margins).grid(row=2,column=0,columnspan=4,sticky='w',padx=7,pady=6)
        entry(canvas,3,'Left margin (%)','margin_left_pct');entry(canvas,3,'Right margin (%)','margin_right_pct',2)
        entry(canvas,4,'Bottom margin (%)','margin_bottom_pct');entry(canvas,4,'Top margin (%)','margin_top_pct',2)
        legends=ttk.LabelFrame(layout,text='Legend',padding=10);legends.pack(fill='x',pady=8)
        enum(legends,0,'Legend position','legend_position',self.POSITIONS)
        entry(legends,0,'Legend font, pt (0 = template)','legend_font_size_pt',2)
        enum(legends,1,'Legend font family','legend_font_family',{'Use template':'template','Arial':'Arial','Microsoft YaHei':'Microsoft YaHei','SimHei':'SimHei','Times New Roman':'Times New Roman'})
        entry(legends,1,'Legend columns (0 = template)','legend_columns',2)
        entry(legends,2,'Legend text color','legend_text_color');ttk.Button(legends,text='Choose color',command=lambda:self.choose_color(self.variables['legend_text_color'])).grid(row=2,column=2,sticky='w',padx=7)
        self.legend_frame=tk.BooleanVar(value=settings['legend_frame']);ttk.Checkbutton(legends,text='Legend frame',variable=self.legend_frame).grid(row=2,column=3,sticky='w')
        entry(legends,3,'Custom X (0 left, 1 right)','legend_anchor_x');entry(legends,3,'Custom Y (0 bottom, 1 top)','legend_anchor_y',2)
        ttk.Label(layout,text='Width and height control the aspect ratio; 0 uses the template. A right-side legend with default width uses a two-column canvas. Custom coordinates locate the legend upper-left corner. Blank text or zero line width uses the template.',wraplength=900,foreground='#135b81').pack(anchor='w',pady=8)
        objects=tabs[2].body
        for column,label in enumerate(['Show / object','Legend label (blank = template)','Line / object color','Line style','Line width (pt)']):ttk.Label(objects,text=label).grid(row=0,column=column,sticky='w',padx=5,pady=8)
        for row,(role,name) in enumerate(SERIES_NAMES.items(),1):
            option=settings['series_options'][role]
            visible=self.density if role=='density' else tk.BooleanVar(value=option['visible'])
            label=tk.StringVar(value=option['label']);color=tk.StringVar(value=option['color']);line=tk.StringVar(value=next(k for k,v in self.LINES.items() if v==option['linestyle']));width=tk.StringVar(value=str(option['linewidth']))
            self.series_variables[role]=dict(visible=visible,label=label,color=color,linestyle=line,linewidth=width)
            ttk.Checkbutton(objects,text=name,variable=visible).grid(row=row,column=0,sticky='w',padx=5,pady=6)
            ttk.Entry(objects,textvariable=label,width=24).grid(row=row,column=1,padx=5)
            colors=ttk.Frame(objects);colors.grid(row=row,column=2,padx=5)
            ttk.Entry(colors,textvariable=color,width=9).pack(side='left');ttk.Button(colors,text='…',width=2,command=lambda var=color:self.choose_color(var)).pack(side='left',padx=3)
            ttk.Combobox(objects,textvariable=line,values=list(self.LINES),state='readonly',width=7).grid(row=row,column=3,padx=5)
            ttk.Entry(objects,textvariable=width,width=6).grid(row=row,column=4,padx=5)
        ttk.Label(objects,text='Applies where the object appears. Hidden objects remain in data tables. Enter #RRGGBB or leave blank. Edit microscopy outlines on the review page.',wraplength=900,foreground='#135b81').grid(row=len(SERIES_NAMES)+1,column=0,columnspan=5,sticky='w',padx=5,pady=12)
        self.enable_fields();self.transient(parent)
        if not hidden:self.grab_set()

    def enable_fields(self):
        mode=self.MODES[self.mode.get()]
        for key,entry in self.bin_entries.items():entry.configure(state='normal' if (key.endswith('_bins') and mode=='count') or (key.endswith('_um') and mode=='width') else 'disabled')

    def value(self):
        values={k:v.get() for k,v in self.variables.items()};values.update({k:mapping[var.get()] for k,(var,mapping) in self.enums.items()})
        values.update(histogram_mode=self.MODES[self.mode.get()],show_density_curve=self.density.get(),curve_style=self.STYLES[self.style.get()],custom_margins=self.custom_margins.get(),legend_frame=self.legend_frame.get())
        values['series_options']={role:{k:(self.LINES[var.get()] if k=='linestyle' else var.get()) for k,var in options.items()} for role,options in self.series_variables.items()}
        return validate_settings(values)

    def choose_color(self,variable):
        from tkinter.colorchooser import askcolor
        color=askcolor(color=variable.get() or '#222222',parent=self)[1]
        if color:variable.set(color)

    def reset_defaults(self):
        defaults=validate_settings()
        for key,var in self.variables.items():var.set(str(defaults[key]))
        for key,(var,mapping) in self.enums.items():var.set(next(k for k,v in mapping.items() if v==defaults[key]))
        self.mode.set(next(k for k,v in self.MODES.items() if v==defaults['histogram_mode']));self.style.set(next(k for k,v in self.STYLES.items() if v==defaults['curve_style']))
        self.custom_margins.set(False);self.legend_frame.set(False)
        for role,options in self.series_variables.items():
            for key,var in options.items():
                value=defaults['series_options'][role][key]
                if key=='linestyle':value=next(k for k,v in self.LINES.items() if v==value)
                var.set(value)
        self.density.set(defaults['show_density_curve']);self.enable_fields()

    def apply_reference_style(self):
        try:settings=reference_style(self.value())
        except (ValueError,TypeError,OverflowError) as e:messagebox.showerror('Check plot settings',error_message(e),parent=self);return
        for key,var in self.variables.items():var.set(str(settings[key]))
        for key,(var,mapping) in self.enums.items():var.set(next(k for k,v in mapping.items() if v==settings[key]))
        self.style.set(next(k for k,v in self.STYLES.items() if v==settings['curve_style']))
        self.custom_margins.set(settings['custom_margins']);self.legend_frame.set(settings['legend_frame'])
        for role,options in self.series_variables.items():
            for key,var in options.items():
                value=settings['series_options'][role][key]
                if key=='linestyle':value=next(k for k,v in self.LINES.items() if v==value)
                var.set(value)
        self.density.set(settings['show_density_curve']);self.enable_fields()

    def accept(self,redraw=False):
        try:settings=self.value();dump(self.case/'plot_settings.json',settings)
        except (ValueError,TypeError,OverflowError,OSError) as e:messagebox.showerror('Check plot settings',error_message(e),parent=self);return
        self.grab_release();self.destroy()
        if self.on_saved:self.on_saved()
        if redraw and self.on_redraw:self.on_redraw()


class SampleIdentityDialog(tk.Toplevel):
    def __init__(self,parent,cases,names,callback):
        super().__init__(parent);self.cases=Path(cases);self.callback=callback
        self.title('Independent sample IDs');fit_window(self,760,650)
        folder=self.cases/'汇总报告';self.path=folder/'sample_identity.json'
        self.data=load(self.path) if self.path.exists() else dict(schema_version=1,cases={})
        footer=ttk.Frame(self,padding=10);footer.pack(side='bottom',fill='x')
        panel=ScrollPanel(self,padding=16);panel.pack(fill='both',expand=True)
        ttk.Label(panel.body,text='Assign a sample ID to each selected case. Images from the same independent sample must share an ID; distinct IDs mean independent samples. Blank IDs disable sample-level confidence intervals for the selection.',wraplength=680).pack(anchor='w',pady=(0,12))
        self.rows=[]
        for name in names:
            case=self.cases/name;meta=load(case/'case.json');prior=self.data.get('cases',{}).get(meta['case_id'],{})
            value=prior.get('sample_id','') if prior.get('source_sha256')==meta.get('source_sha256') else ''
            row=ttk.Frame(panel.body);row.pack(fill='x',pady=4);ttk.Label(row,text=name,width=35).pack(side='left');var=tk.StringVar(value=value);ttk.Entry(row,textvariable=var,width=32).pack(side='left');self.rows.append((meta,var))
        ttk.Button(footer,text='Cancel',command=self.destroy).pack(side='right',padx=8)
        ttk.Button(footer,text='Save sample IDs',command=self.accept).pack(side='right')
        self.transient(parent);self.grab_set()
    def accept(self):
        entries=self.data.setdefault('cases',{})
        for meta,var in self.rows:
            value=var.get().strip()
            if len(value)>120:messagebox.showerror('Check sample IDs','Sample IDs must be at most 120 characters.',parent=self);return
            if value:entries[meta['case_id']]=dict(sample_id=value,source_sha256=meta.get('source_sha256'),declared_at=datetime.now().isoformat())
            else:entries.pop(meta['case_id'],None)
        try:dump(self.path,self.data)
        except OSError as e:messagebox.showerror('Cannot save sample IDs',error_message(e),parent=self);return
        self.grab_release();self.destroy();self.callback()


class App(tk.Tk):
    def __init__(self,cases=None,hidden=False):
        super().__init__()
        if hidden:self.withdraw()
        self.title('EOH — Eyes of heaven | 0.4.1');fit_window(self,1040,760)
        settings=load(ROOT/'desktop_settings.json') if (ROOT/'desktop_settings.json').exists() else {}
        self.cases=validate_output_root(cases or settings.get('output_directory',ROOT.parent/'分析结果'));self.cases.mkdir(parents=True,exist_ok=True)
        self.input_directory=tk.StringVar(value=settings.get('input_directory',str(ROOT.parent/'FIGURES')));self.output_directory=tk.StringVar(value=str(self.cases));self.pending_files=[];self.pending_jobs=[]
        self.runtime=tempdir(ROOT/'_tmp','desktop');configure_temp(self.runtime)
        self.worker=None;self.events=queue.Queue();self.job=None;self.failed=False;self.port=None;self.revision=None;self.stopping=False;self.closing=False;self.poll_after=None;self.checked_cases=set()
        self.confirm=tk.BooleanVar(value=False);self.status=tk.StringVar(value='Import an image to begin, or select the folder containing your existing cases.')
        self.scroll=ScrollPanel(self,padding=15);self.scroll.pack(fill='both',expand=True);outer=self.scroll.body
        ttk.Label(outer,text='EOH — Eyes of heaven · Import → Review and save → Generate report',font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w',pady=(0,10))
        paths=ttk.Frame(outer);paths.pack(fill='x',pady=(0,8))
        ttk.Label(paths,text='Input image folder').grid(row=0,column=0,sticky='w');ttk.Entry(paths,textvariable=self.input_directory,width=90).grid(row=0,column=1,sticky='ew',padx=6);ttk.Button(paths,text='Browse',command=self.choose_input_folder).grid(row=0,column=2)
        ttk.Label(paths,text='Output case folder').grid(row=1,column=0,sticky='w');ttk.Entry(paths,textvariable=self.output_directory,width=90,state='readonly').grid(row=1,column=1,sticky='ew',padx=6);ttk.Button(paths,text='Browse',command=self.choose_output_folder).grid(row=1,column=2);paths.columnconfigure(1,weight=1)
        bar=ttk.Frame(outer);bar.pack(fill='x')
        self.import_button=ttk.Button(bar,text='1. Import image',command=self.choose);self.import_button.pack(side='left',padx=(0,10))
        self.review_button=ttk.Button(bar,text='2. Open review',command=self.open_review);self.review_button.pack(side='left',padx=(0,10))
        self.report_button=ttk.Button(bar,text='3. Generate report',command=self.generate);self.report_button.pack(side='left',padx=(0,10))
        self.cancel_button=ttk.Button(bar,text='Stop calculation',command=self.cancel,state='disabled');self.cancel_button.pack(side='left')
        ttk.Button(bar,text='Batch import',command=self.batch_import).pack(side='left',padx=6)
        ttk.Button(bar,text='Batch candidate analysis',command=self.batch_analyze).pack(side='left')
        ttk.Button(bar,text='Chinese manual',command=lambda:os.startfile(str(ROOT/'操作说明.html' if FROZEN else ROOT.parent/'EOH_中文说明手册.html'))).pack(side='right')
        compute=ttk.Frame(outer);compute.pack(fill='x',pady=(7,0));ttk.Label(compute,text='Compute device').pack(side='left')
        self.backend=tk.StringVar(value={'auto':'Auto (prefer GPU)','cpu':'CPU only','gpu':'Prefer GPU (CPU fallback)'}.get(settings.get('compute_backend','auto'),'Auto (prefer GPU)'))
        selector=ttk.Combobox(compute,textvariable=self.backend,values=['Auto (prefer GPU)','CPU only','Prefer GPU (CPU fallback)'],state='readonly',width=25);selector.pack(side='left',padx=8);selector.bind('<<ComboboxSelected>>',lambda event:self.save_settings())
        ttk.Label(compute,text='Accelerates uniform and equal-area random layouts; the report records the device used.').pack(side='left')
        self.tree=ttk.Treeview(outer,columns=['checked','name','size','saved','report'],show='headings',height=8,selectmode='browse')
        for key,label,width in [('checked','Select',48),('name','Case name',300),('size','Image pixels / μm per pixel',230),('saved','Saved review',100),('report','Latest report',180)]:
            self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=70)
        self.tree.column('checked',width=48,minwidth=48,stretch=False,anchor='center')
        self.tree.pack(fill='x',pady=12);self.tree.bind('<<TreeviewSelect>>',lambda e:self.selected());self.tree.bind('<Button-1>',self.check_clicked);self.tree.bind('<space>',self.check_keyboard)
        selection=ttk.Frame(outer);selection.pack(fill='x',pady=(0,7))
        ttk.Button(selection,text='Select all',command=lambda:self.check_all(True)).pack(side='left',padx=(0,8))
        ttk.Button(selection,text='Clear selection',command=lambda:self.check_all(False)).pack(side='left',padx=(0,8))
        self.summary_button=ttk.Button(selection,text='Export batch summary',command=self.batch_summary);self.summary_button.pack(side='left',padx=(0,12))
        ttk.Button(selection,text='Open latest summary',command=self.open_latest_summary).pack(side='left',padx=(0,12))
        self.summary_settings_button=ttk.Button(selection,text='Summary plot settings',command=self.edit_summary_settings);self.summary_settings_button.pack(side='left',padx=(0,8))
        self.replot_button=ttk.Button(selection,text='Redraw latest summary',command=self.replot_summary);self.replot_button.pack(side='left',padx=(0,8))
        self.selection_label=tk.StringVar(value='0 cases selected');ttk.Label(selection,textvariable=self.selection_label).pack(side='left')
        samplebar=ttk.Frame(outer);samplebar.pack(fill='x',pady=(0,5))
        self.sample_button=ttk.Button(samplebar,text='Set sample IDs for selected cases',command=self.edit_sample_ids);self.sample_button.pack(side='left')
        ttk.Label(samplebar,text='Required for sample-level grain-size confidence intervals.').pack(side='left',padx=8)
        self.detail=tk.StringVar();ttk.Label(outer,textvariable=self.detail,wraplength=980).pack(anchor='w')
        self.check=ttk.Checkbutton(outer,text='I checked scale, crop, window W and bright/dark outlines, then clicked Save all changes on the review page.',variable=self.confirm)
        self.check.pack(anchor='w',pady=12)
        actions=ttk.Frame(outer);actions.pack(fill='x')
        ttk.Button(actions,text='Open latest report',command=self.open_report).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Open grain-size report',command=self.open_grain_report).pack(side='left',padx=(0,8))
        self.plot_button=ttk.Button(actions,text='Plot settings',command=self.edit_plot_settings);self.plot_button.pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Open case folder',command=lambda:self.open_folder(False)).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Open exported results',command=lambda:self.open_folder(True)).pack(side='left',padx=(0,8))
        ttk.Button(actions,text='Restore review backup',command=self.restore).pack(side='left')
        self.enhance_button=ttk.Button(actions,text='Enhance bright-grain detection',command=self.enhance_bright);self.enhance_button.pack(side='left',padx=(8,0))
        ttk.Label(outer,textvariable=self.status,wraplength=980,foreground='#135b81').pack(anchor='w',pady=(14,6))
        self.progress=ttk.Progressbar(outer,mode='indeterminate');self.progress.pack(fill='x')
        self.log=tk.Text(outer,height=11,wrap='word',state='disabled',font=('Microsoft YaHei UI',10));self.log.pack(fill='both',expand=True,pady=8)
        ttk.Label(outer,text='Results are archived by case and review revision: separate figures, distance tables, random layouts, methods and PDF reports. Figures are also saved as PDF/SVG/PNG/TIFF.',wraplength=980).pack(anchor='w')
        self.protocol('WM_DELETE_WINDOW',self.close);self.refresh();self.poll_after=self.after(150,self.poll)
    def current(self):
        keys=self.tree.selection()
        return self.cases/keys[0] if keys else None
    def say(self,text):
        self.status.set(text);self.log.configure(state='normal');self.log.insert('end',datetime.now().strftime('%H:%M:%S')+'  '+text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def refresh(self,select=None):
        selected=select or (self.current().name if self.current() else None)
        seen=set()
        for p in sorted(self.cases.iterdir(),reverse=True):
            if not p.is_dir() or not (p/'case.json').exists():continue
            try:
                m=load(p/'case.json');r=load(p/'report'/'review_annotations'/'review_annotations.json');latest=load(p/'latest_report.json') if (p/'latest_report.json').exists() else {}
                rev=latest.get('review_revision');label='Not generated' if rev is None else f"r{rev}"+(' (update needed)' if rev!=r['revision'] else ' (candidate)' if not latest.get('human_review_confirmed',True) else '')
                if rev is not None and (read_settings(p)!=validate_settings(latest.get('plot_settings')) or 'random_curve_count' not in (latest.get('plot_settings') or {})):label+=' (plots need update)'
                values=['☑' if p.name in self.checked_cases else '☐',m['name'],f"{m['cropped_dimensions'][0]}×{m['cropped_dimensions'][1]} / {m['pixel_size_um']:.7g}",f"r{r['revision']}",label]
                seen.add(p.name)
                if self.tree.exists(p.name):self.tree.item(p.name,values=values)
                else:self.tree.insert('',tk.END,iid=p.name,values=values)
            except (OSError,KeyError,ValueError):continue
        for key in self.tree.get_children():
            if key not in seen:self.tree.delete(key)
        self.checked_cases.intersection_update(seen)
        if selected and self.tree.exists(selected):self.tree.selection_set(selected)
        elif self.tree.get_children():self.tree.selection_set(self.tree.get_children()[0])
        self.selection_label.set(f'Selected: {len(self.checked_cases)} cases')
        self.selected()
    def toggle_check(self,key):
        if key in self.checked_cases:self.checked_cases.remove(key)
        else:self.checked_cases.add(key)
        self.tree.set(key,'checked','☑' if key in self.checked_cases else '☐');self.selection_label.set(f'Selected: {len(self.checked_cases)} cases')
    def check_clicked(self,event):
        key=self.tree.identify_row(event.y)
        if key and self.tree.identify_column(event.x)=='#1' and self.tree.identify_region(event.x,event.y)=='cell':
            self.tree.selection_set(key);self.toggle_check(key);return 'break'
    def check_keyboard(self,event):
        for key in self.tree.selection():self.toggle_check(key)
        return 'break'
    def check_all(self,value):
        self.checked_cases=set(self.tree.get_children()) if value else set()
        for key in self.tree.get_children():self.tree.set(key,'checked','☑' if value else '☐')
        self.selection_label.set(f'Selected: {len(self.checked_cases)} cases')
    def selected(self):
        p=self.current()
        if not p:self.detail.set('Each image has a separate case; a copy of the original is archived.');return
        try:
            r=load(p/'report'/'review_annotations'/'review_annotations.json');binding=(p.name,r['revision'])
            if binding!=self.revision:self.confirm.set(False);self.revision=binding
            self.detail.set(f"Saved revision r{r['revision']}; active edits: {len(r['active_ids'])}. Case folder: {p}")
        except (OSError,ValueError,KeyError):pass
    def choose(self):
        f=filedialog.askopenfilename(parent=self,title='Select a single-frame 8-bit BSE image',initialdir=self.input_directory.get(),filetypes=[('Images','*.tif *.tiff *.png *.bmp *.jpg *.jpeg'),('All files','*.*')])
        if f:
            try:ImportDialog(self,f,self.start_import)
            except Exception as e:messagebox.showerror('Cannot open image',error_message(e),parent=self)
    def start_import(self,spec):
        path=self.runtime/'import_spec.json';dump(path,spec);self.run(['import','--spec',str(path),'--cases-root',str(self.cases)])
    def enhance_bright(self):
        if self.worker:return
        case=self.require_case()
        if case:
            def create(options):
                path=self.runtime/'bright_options.json';dump(path,options)
                self.run(['enhance-bright','--case',str(case),'--spec',str(path),'--cases-root',str(self.cases)])
            BrightDetectionDialog(self,case,create)
    def save_settings(self):dump(ROOT/'desktop_settings.json',dict(input_directory=self.input_directory.get(),output_directory=str(self.cases),compute_backend={'Auto (prefer GPU)':'auto','CPU only':'cpu','Prefer GPU (CPU fallback)':'gpu'}[self.backend.get()]))
    def choose_input_folder(self):
        path=filedialog.askdirectory(parent=self,title='Select input image folder',initialdir=self.input_directory.get())
        if path:self.input_directory.set(path);self.save_settings()
    def choose_output_folder(self):
        if self.worker:messagebox.showinfo('Calculation in progress','Wait for the current calculation before changing the output folder.',parent=self);return
        path=filedialog.askdirectory(parent=self,title='Select output folder' if FROZEN else 'Select output folder on drive E',initialdir=str(self.cases))
        if not path:return
        try:
            self.cases=validate_output_root(path);self.output_directory.set(str(self.cases));self.port=None;self.confirm.set(False);self.revision=None;self.checked_cases.clear()
            for row in self.tree.get_children():self.tree.delete(row)
            self.save_settings();self.refresh()
        except UserError as e:messagebox.showerror('Invalid output folder',error_message(e),parent=self)
    def batch_import(self):
        if self.worker:return
        folder=Path(self.input_directory.get())
        if not folder.is_dir():messagebox.showerror('Input folder not found','Select a valid image folder.',parent=self);return
        self.pending_files=sorted(p for p in folder.iterdir() if p.suffix.lower() in ['.tif','.tiff','.png','.jpg','.jpeg','.bmp']);self.next_import()
    def next_import(self):
        if not self.pending_files:return
        from image_calibration import known_calibration
        source=self.pending_files.pop(0);calibration=known_calibration(source)
        import hashlib
        fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()
        if any(load(p/'case.json').get('source_sha256')==fingerprint for p in self.cases.iterdir() if p.is_dir() and (p/'case.json').exists()):
            self.say(source.name+' already exists in this output folder; its review and results are retained.');self.after(100,self.next_import);return
        if calibration:
            self.start_import(dict(source=str(source),name=source.stem,crop=calibration['crop'],pixel_size_um=calibration['pixel_size_um'],calibration=calibration,auto_domain=True,adaptive_segmentation=True,analysis=dict(exclusive_phases=True)))
        else:
            self.say(source.name+' has no verified scale. Set calibration in the dialog, then create candidates.')
            ImportDialog(self,source,self.start_import)
    def batch_analyze(self):
        if self.worker:return
        names=[p.name for p in self.cases.iterdir() if p.is_dir() and (p/'case.json').exists()]
        if not names:messagebox.showinfo('No cases','Import an image first.',parent=self);return
        self.batch_cancel=self.runtime/'batch_cancel.flag';self.batch_cancel.unlink(missing_ok=True)
        path=self.runtime/'batch_selection.json';dump(path,dict(cases=names))
        self.run(['analyze-batch','--selection',str(path),'--cases-root',str(self.cases),'--cancel-file',str(self.batch_cancel)])
    def next_analysis(self):
        if not self.pending_jobs:return
        p=self.pending_jobs.pop(0);r=load(p/'report'/'review_annotations'/'review_annotations.json');self.run(['analyze','--case',str(p),'--cases-root',str(self.cases),'--confirmed-revision',str(r['revision']),'--candidate'])
    def batch_summary(self):
        if self.worker:return
        names=[key for key in self.tree.get_children() if key in self.checked_cases]
        if not names:messagebox.showinfo('Select cases first','Check the boxes beside the cases to include in the summary.',parent=self);return
        path=self.runtime/'summary_selection.json';dump(path,dict(cases=names))
        self.run(['summarize','--selection',str(path),'--cases-root',str(self.cases)])
    def edit_sample_ids(self):
        if self.worker:return
        names=[key for key in self.tree.get_children() if key in self.checked_cases]
        if not names:messagebox.showinfo('Select cases first','Check the cases whose independent sample IDs you want to edit.',parent=self);return
        try:SampleIdentityDialog(self,self.cases,names,lambda:self.say('Sample IDs saved. Re-export or redraw the summary to apply them.'))
        except (ValueError,OSError,KeyError) as e:messagebox.showerror('Cannot edit sample IDs',error_message(e),parent=self)
    def open_latest_summary(self):
        path=self.cases/'汇总报告'/'latest_summary.json'
        if path.exists():
            report=Path(load(path)['report'])
            if report.exists():os.startfile(str(report));return
        messagebox.showinfo('No summary report','Select cases, then click Export batch summary.',parent=self)
    def edit_summary_settings(self):
        if self.worker:return
        folder=self.cases/'汇总报告';initial=None
        if not (folder/'plot_settings.json').exists():
            if (folder/'latest_summary.json').exists():
                root=Path(load(folder/'latest_summary.json')['report']).parent
                if (root/'inputs'/'plot_settings.json').exists():initial=load(root/'inputs'/'plot_settings.json')
            if initial is None:initial=read_settings(self.current()) if self.current() else validate_settings()
        try:PlotSettingsDialog(self,folder,lambda:self.say('Summary plot settings saved. Click Redraw latest summary to apply them to saved results. They also apply to the next batch summary.'),initial_settings=initial,on_redraw=self.replot_summary,scope='summary')
        except (ValueError,OSError) as e:messagebox.showerror('Cannot read summary settings',error_message(e),parent=self)
    def replot_summary(self):
        if self.worker:return
        if not (self.cases/'汇总报告'/'latest_summary.json').exists():messagebox.showinfo('No summary report','Select cases and export a batch summary first.',parent=self);return
        previous=Path(load(self.cases/'汇总报告'/'latest_summary.json')['report']).parent
        if not (previous/'inputs'/'selection.json').exists() or not (previous/'inputs'/'source_manifest.json').exists():
            messagebox.showinfo('Summary folder moved or deleted','The recorded summary folder is missing or incomplete. Select cases and click Export batch summary again; saved outlines are retained.',parent=self);return
        self.run(['replot-summary','--cases-root',str(self.cases)])
    def run(self,args):
        if self.worker:return
        self.failed=False;self.job=None;self.progress.start(12)
        for b in [self.import_button,self.report_button,self.plot_button,self.summary_button,self.summary_settings_button,self.replot_button,self.enhance_button,self.sample_button]:b.configure(state='disabled')
        self.cancel_button.configure(state='normal' if args[0] in ['analyze','analyze-batch','summarize','replot-summary','enhance-bright'] else 'disabled')
        env=dict(os.environ);env['BSE_COMPUTE_BACKEND']={'Auto (prefer GPU)':'auto','CPU only':'cpu','Prefer GPU (CPU fallback)':'gpu'}[self.backend.get()]
        self.worker=subprocess.Popen(process_command('engine',*args),cwd=ROOT,env=env,creationflags=HIDDEN,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
        process=self.worker
        def read():
            for line in process.stdout:
                try:self.events.put(json.loads(line))
                except ValueError:self.events.put(dict(event='raw',message=line.strip()))
            process.stdout.close();self.events.put(dict(event='exit',code=process.wait()))
        threading.Thread(target=read,daemon=True).start();self.say('Processing. Previous reviews and reports remain available.')
    def poll(self):
        if self.closing:return
        self.poll_after=None
        while not self.events.empty():
            e=self.events.get();kind=e.get('event')
            if e.get('job'):self.job=Path(e['job'])
            if kind=='exit':
                self.worker=None;self.job=None;self.progress.stop()
                for b in [self.import_button,self.report_button,self.plot_button,self.summary_button,self.summary_settings_button,self.replot_button,self.enhance_button,self.sample_button]:b.configure(state='normal')
                self.cancel_button.configure(state='disabled');self.refresh()
                if e['code'] and not self.failed:self.say('Calculation did not finish. Check the messages below or the error log in the case logs folder.')
                if self.stopping:self.finish_close();return
                if self.pending_files:self.after(100,self.next_import)
                elif self.pending_jobs:self.after(100,self.next_analysis)
            elif kind=='error':
                self.failed=True;self.say(e['message']+'\nDetailed log: '+e.get('log',''))
                if not self.stopping:messagebox.showerror('No report published for this task',e['message']+'\n\n'+e.get('log',''),parent=self)
            elif kind=='complete':
                self.say(e['message']);self.refresh(Path(e['case']).name)
                if e.get('open_review') and not self.stopping:self.open_review()
                if e.get('report') and not e.get('batch_item') and not self.stopping and not self.pending_jobs:os.startfile(e['report'])
            elif e.get('message'):self.say(e['message'])
        self.selected()
        if not self.worker:self.refresh()
        self.poll_after=self.after(700,self.poll)
    def status_at(self,port):
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/status',timeout=.35) as r:return json.load(r)
        except Exception:return None
    def ensure_server(self):
        if self.port and self.status_at(self.port):return self.port
        for port in range(8766,8797):
            status=self.status_at(port)
            if status:
                if status.get('service')=='bse-self-service' and Path(status.get('cases_root','')).resolve()==self.cases:self.port=port;return port
                continue
            logpath=ROOT/'logs'/'self_service_server.log';logpath.parent.mkdir(exist_ok=True)
            env=dict(os.environ);env.update(TEMP=str(ROOT/'_tmp'),TMP=str(ROOT/'_tmp'),TMPDIR=str(ROOT/'_tmp'))
            with logpath.open('a',encoding='utf-8') as f:
                proc=subprocess.Popen(process_command('server','--port',str(port),'--cases-root',str(self.cases)),cwd=ROOT,env=env,creationflags=HIDDEN,stdout=f,stderr=f)
            for _ in range(12):
                time.sleep(.1);status=self.status_at(port)
                if status and status.get('service')=='bse-self-service' and Path(status.get('cases_root','')).resolve()==self.cases:self.port=port;return port
                if proc.poll() is not None:break
        raise RuntimeError('Cannot start the local review service. Check case logs and logs/self_service_server.log.')
    def require_case(self):
        p=self.current()
        if not p:messagebox.showinfo('Select a case first','Import an image or select a case in the list.',parent=self)
        return p
    def open_review(self):
        p=self.require_case()
        if not p:return
        try:
            port=self.ensure_server();key=load(p/'case.json')['case_id'];webbrowser.open(f'http://127.0.0.1:{port}/case/{key}/review/');self.say('Check orange window W; add hole points / crack lines and review bright/dark outlines. Finish by clicking Save all changes.')
        except Exception as e:messagebox.showerror('Review service unavailable',error_message(e),parent=self)
    def generate(self):
        p=self.require_case()
        if not p:return
        self.selected()
        if not self.confirm.get():messagebox.showinfo('Human review required','Check scale, window W and bright/dark outlines; save all changes on the review page, then check the review confirmation here.',parent=self);return
        r=load(p/'report'/'review_annotations'/'review_annotations.json');self.run(['analyze','--case',str(p),'--cases-root',str(self.cases),'--confirmed-revision',str(r['revision'])])
    def edit_plot_settings(self):
        if self.worker:return
        p=self.require_case()
        if p:
            try:PlotSettingsDialog(self,p,lambda:(self.refresh(p.name),self.say('Case plot settings saved. They apply when generating reports, exporting batch summaries or redrawing the latest summary. Reimporting and redrawing outlines are unnecessary.')))
            except (ValueError,OSError) as e:messagebox.showerror('Cannot read plot settings',error_message(e),parent=self)
    def open_report(self):
        p=self.require_case()
        if not p:return
        if not (p/'latest_report.json').exists():messagebox.showinfo('Not generated','Review and save, then click Generate report.',parent=self);return
        os.startfile(load(p/'latest_report.json')['report'])
    def open_folder(self,export=False):
        p=self.require_case()
        if not p:return
        if export and (p/'latest_report.json').exists():p=p/'results'/load(p/'latest_report.json')['run']
        os.startfile(str(p))
    def open_grain_report(self):
        p=self.require_case()
        if p and (p/'latest_report.json').exists():os.startfile(load(p/'latest_report.json').get('grain_report',load(p/'latest_report.json')['report']))
    def restore(self):
        p=self.require_case()
        if not p:return
        f=filedialog.askopenfilename(parent=self,title='Restore a complete review backup for this case',initialdir=str(p/'report'/'review_annotations'),filetypes=[('Review records','*.json')])
        if not f:return
        try:
            incoming=load(f);meta=load(p/'case.json')
            if incoming.get('dataset_id')!=meta['dataset_id'] or incoming.get('schema_version')!=1:raise ValueError('This backup belongs to another case. Select a matching backup.')
            if not messagebox.askyesno('Restore full review state','The backup will replace the current review and be saved as a new revision. The current state is backed up automatically.\nStop editing the review page first; refresh it after restoring.',parent=self):return
            port=self.ensure_server();url=f'http://127.0.0.1:{port}/case/{meta["case_id"]}/api/reviews'
            with urlopen(url,timeout=3) as r:current=json.load(r)
            incoming['base_revision']=current['revision']
            request=Request(url,data=json.dumps(incoming).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
            with urlopen(request,timeout=5) as r:result=json.load(r)
            self.say(f"Restored review r{result['revision']}. Refresh the review page, check the result and regenerate the report.");self.refresh()
        except Exception as e:messagebox.showerror('Restore failed',error_message(e),parent=self)
    def cancel(self):
        self.pending_files=[];self.pending_jobs=[]
        if getattr(self,'batch_cancel',None):self.batch_cancel.write_text('cancel',encoding='utf-8')
        if self.job and self.job.is_relative_to(self.cases) and (self.job/'.temporary-owner.json').exists():
            (self.job/'cancel.flag').write_text('cancel',encoding='utf-8');self.say('Stop requested. Temporary results will be cleaned after the current calculation step.')
        else:self.say('Preparing. Try Stop again shortly.')
    def close(self):
        if self.worker and self.worker.poll() is not None:self.worker=None
        if self.worker:
            if not self.job:messagebox.showinfo('Preparing','Import / preparation is in progress. Wait for it to finish before closing.',parent=self);return
            if not messagebox.askyesno('Stop calculation and close?','Original images, review records and previous reports will be retained. Unfinished temporary results from this run will be removed.',parent=self):return
            self.stopping=True;self.cancel();return
        self.finish_close()
    def finish_close(self):
        if self.closing:return
        self.closing=True;self.withdraw()
        if self.poll_after:
            try:self.after_cancel(self.poll_after)
            except tk.TclError:pass
            self.poll_after=None
        cleanup=dict(runtime=str(self.runtime),closed=True)
        try:
            if self.runtime.exists():safe_remove(self.runtime,ROOT/'_tmp')
            cleanup['temporary_removed']=True
        except Exception as e:
            cleanup.update(temporary_removed=False,error=error_message(e),retained_path=str(self.runtime))
            print('Runtime cache retained on exit: '+str(self.runtime)+'；'+error_message(e),flush=True)
        finally:
            try:dump(ROOT/'logs'/'desktop_cleanup.json',cleanup)
            except OSError:pass
            self.destroy()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cases-root',type=Path);args=parser.parse_args()
    app=App(args.cases_root);app.mainloop()
