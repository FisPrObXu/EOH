// Point and open-polyline buffers are persisted in the same revision as mineral outlines.
if(DATA.editable_exclusions){
 Object.assign(OPS,{add_exclusion:'Add exclusion',replace_exclusion:'Change exclusion radius',delete_exclusion:'Delete exclusion'});
 const panel=document.createElement('div');panel.className='toolbar';panel.id='exclusion-tools';
 panel.innerHTML='<b>Exclusions</b><button id="hole-point">Hole: place point</button><button id="crack-line">Crack: draw line</button><label>Exclusion radius <input id="buffer-radius" type="number" min="0.001" step="0.1" value="1" style="width:90px"> μm</label><label>Existing exclusions<select id="exclusion-list"></select></label><button id="change-buffer">Change selected radius</button><button id="remove-buffer" class="danger">Delete selected exclusion</button><span class="muted">Default radius: holes 1 μm, cracks 0.5 μm. Orange W includes the distance-limit edge guard.</span>';
 document.querySelector('.workspace').before(panel);$('show-A').checked=true;
 const mode=document.createElement('label');mode.innerHTML='Safe window <select id="window-mode"><option value="distance">Distance tests</option><option value="size">Grain sizes</option></select><span id="window-guard-note" class="muted"></span>';panel.append(mode);
 let distancePaths=FIELDS[FIELD_IDS[0]].window_paths;
 function displayWindow(){const field=FIELDS[currentField()],size=$('window-mode').value==='size';windowPixels[currentField()]=unpack(size&&field.size_W_runs?field.size_W_runs:field.W_runs,field.width*field.height);field.window_paths=size&&field.size_window_paths?field.size_window_paths:distancePaths;$('window-guard-note').textContent=`Current ${size?'grain-size':'distance'} edge guard: ${size?(field.size_guard_um??1):(field.distance_guard_um??5)} μm; grain-size statistics require the complete grain inside the window.`;rebuild();draw();}
 $('window-mode').onchange=displayWindow;
 let previewSequence=0;
 function radius(){const r=Number($('buffer-radius').value);if(!Number.isFinite(r)||r<=0)throw Error('Exclusion radius must be positive, in μm.');return r;}
 function choices(){const select=$('exclusion-list'),old=select.value;select.replaceChildren(...(FIELDS[currentField()].exclusion_shapes||[]).map(s=>new Option(`${s.id} · ${s.kind==='point'?'Hole':s.kind==='line'?'Crack':'Rectangle'} · ${s.radius_um||0} μm`,s.id)));if([...select.options].some(o=>o.value===old))select.value=old;}
 function selectedExclusion(){return (FIELDS[currentField()].exclusion_shapes||[]).find(s=>s.id===$('exclusion-list').value);}
 function newExclusionId(){const used=new Set(state.actions.map(a=>a.object_id));let k=1;while(used.has('EX'+String(k).padStart(4,'0')))k++;return 'EX'+String(k).padStart(4,'0');}
 function addExclusion(points,kind){try{const r=radius();action('add_exclusion',{object_id:newExclusionId(),geometry:{kind,points:points.map(p=>p.map(v=>Math.round(v*100)/100)),radius_um:r}});cancel();$('hint').textContent=`Recorded ${kind==='point'?'hole point':'crack line'}, radius ${r} μm; saving updates red exclusions and orange W.`;}catch(e){$('hint').textContent=e.message;}}
 async function updateContext(){
  const token=++previewSequence;const response=await fetch(API_BASE+'/api/context-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state)});
  const field=await response.json();if(!response.ok)throw Error(field.error||'Exclusion preview failed');if(token!==previewSequence)return;
  const i=currentField();Object.assign(FIELDS[i],field);distancePaths=field.window_paths;windowPixels[i]=unpack(field.W_runs,FIELDS[i].width*FIELDS[i].height);contextPixels[i]=unpack(field.A_runs,FIELDS[i].width*FIELDS[i].height);
  const im=new Image();im.src=field.exclusion_image;await im.decode();if(token!==previewSequence)return;exclusionImages[i]=im;choices();displayWindow();
  if(!field.W_runs.length)$('hint').textContent='W is empty. Check scale, or reduce / delete exclusions.';
 }
 const persist=save;
 save=async function(){await persist();if(!dirty&&!blocked){try{await updateContext();}catch(e){$('hint').textContent='Records saved, but preview not updated: '+e.message+'. Refresh the review page.';}}};
 const finishOutline=finish;
 finish=function(){if(ui.mode==='exclude-line'){if(ui.draft.length<2){$('hint').textContent='A crack needs at least two points.';return;}addExclusion(ui.draft,'line');}else finishOutline();};
 const refreshOutline=refresh;
 refresh=function(){refreshOutline();if(ui.mode==='exclude-line')$('finish').disabled=ui.draft.length<2;};
 const rebuildOutlines=rebuild;rebuild=function(){rebuildOutlines();for(const [i,objects] of Object.entries(models))for(const r of objects.values())r.in_W=pixelAt(i,[r.centroid_x_px,r.centroid_y_px],'W');};
 $('finish').onclick=()=>finish();
 $('hole-point').onclick=()=>{cancel();ui.mode='exclude-point';$('buffer-radius').value='1';$('hint').textContent='Set the radius, then click the hole center. The red disk is excluded from statistics.';refresh();};
 $('crack-line').onclick=()=>{begin('exclude-line');$('buffer-radius').value='0.5';$('hint').textContent='Set the radius and trace the crack. For vertices, press Enter to finish. The line stays open; endpoints use the same buffer radius.';};
 for(const id of ['raw','overlay'])$(id).addEventListener('pointerdown',e=>{if(ui.mode!=='exclude-point'||!ready||e.button!==0)return;const p=nativePoint(e);if(!inside(p))return;e.stopImmediatePropagation();e.preventDefault();addExclusion([p],'point');},true);
 $('exclusion-list').onchange=()=>{const s=selectedExclusion();if(s)$('buffer-radius').value=s.radius_um||1;};
 $('change-buffer').onclick=()=>{const s=selectedExclusion();if(!s)return;try{action('replace_exclusion',{object_id:s.id,geometry:{kind:s.kind,points:s.points,radius_um:radius()}});}catch(e){$('hint').textContent=e.message;}};
 $('remove-buffer').onclick=()=>{const s=selectedExclusion();if(s)action('delete_exclusion',{object_id:s.id});};
 const initOutlines=init;init=async function(){await initOutlines();await updateContext();};
}
