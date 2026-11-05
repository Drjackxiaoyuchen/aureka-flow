/* Local UI. Only geometry is sent to FlowKit; displayed event indices never define gates. */
const $ = id => document.getElementById(id);
const colors = ['#4200ac', '#6fc0a9', '#9270cf', '#3d328f', '#a6d7c8', '#b49ae2'];
const startup = new URLSearchParams(window.location.search);
const state = {samples: [], gates: [], selected: startup.get('sample'), population: 'root', tab: 'explore',
  selection: null, tool: 'select', view: null, revision: 0, compareIds: new Set(), busy: 0, dirty: false};
const fmt = v => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: 3});
const pct = v => v == null ? '—' : `${Number(v).toFixed(2)}%`;
const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function notice(message, error=false) {
  $('notice').textContent = message; $('notice').classList.toggle('error', error); $('notice').hidden = !message;
}
async function api(url, data, method) {
  const options = {method: method || (data === undefined ? 'GET' : 'POST')};
  if (data instanceof FormData) options.body = data;
  else if (data !== undefined) {options.headers = {'Content-Type': 'application/json'}; options.body = JSON.stringify(data);}
  const response = await fetch(url, options);
  if (!response.ok) {
    let body; try {body = await response.json();} catch {throw new Error(`Server returned ${response.status}.`);}
    const detail = body.detail;
    throw new Error(Array.isArray(detail) ? detail.map(e => `${e.loc?.slice(1).join('.') || 'Input'}: ${e.msg}`).join('\n') : detail || 'Request failed.');
  }
  return response;
}
async function json(url, data, method) {return (await api(url, data, method)).json();}
async function run(action, label='Calculating across all events…') {
  state.busy++; $('busy-label').textContent = label; $('busy').hidden = false;
  document.querySelectorAll('button, #loaded select').forEach(x => x.disabled = true);
  try {await action();} catch (error) {notice(error.message || String(error), true);}
  finally {
    state.busy--; if (!state.busy) {$('busy').hidden = true; document.querySelectorAll('button, #loaded select').forEach(x => x.disabled = false);}
  }
}
async function download(url, data, filename) {
  const response = await api(url, data);
  const blob = await response.blob(), link = document.createElement('a'), href = URL.createObjectURL(blob);
  link.href = href; link.download = filename; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 30000);
}
const current = () => state.samples.find(x => x.id === state.selected);
function transform(axis) {
  const result = {kind: $(`${axis}-scale`).value};
  for (const key of ['t','m','w','a']) {
    const input = $(`${axis}-${key}`);
    if (input.value === '') throw new Error('Transform parameters cannot be empty.');
    result[key] = Number(input.value);
  }
  return result;
}
function axisSpec(axis) {return {channel: $(`${axis}-channel`).value, transform: transform(axis)};}
function viewSpec() {return {sample_id: state.selected, x: axisSpec('x'), y: axisSpec('y'), compensation: $('compensation').value, population: state.population, max_points: 25000};}
function comparisonSpec() {
  return {sample_ids: state.samples.filter(x => state.compareIds.has(x.id)).map(x => x.id),
    x: axisSpec('x'), y: axisSpec('y'), compensation: $('compensation').value, population: $('compare-population').value || 'root',histogram_axis: $('histogram-axis').value};
}
function setAxis(axis, spec) {
  $(`${axis}-channel`).value = spec.channel; $(`${axis}-scale`).value = spec.transform.kind;
  for (const key of ['t','m','w','a']) $(`${axis}-${key}`).value = spec.transform[key];
}
function labelAxis(axis) {
  const spec = axisSpec(axis), ch = current()?.channels.find(x => x.id === spec.channel);
  return `${ch?.label || spec.channel} · ${spec.transform.kind === 'linear' ? 'linear' : spec.transform.kind + ' transformed'}`;
}
function resetSelection() {
  state.selection = null;
  ['x-min','x-max','y-min','y-max','expression-threshold','binding-threshold'].forEach(id => $(id).value = '');
  $('selection-note').textContent = state.tool==='lasso' ? 'Drag to trace a polygon on the plot. Release to finish, then save your gate.' : 'Drag a rectangle on the plot, or enter bounds below. Then name and save your gate.';
  $('selection-ready').hidden = true;
  document.querySelector('.bounds-grid').hidden = false;
}
function renderSamples() {
  $('sample-count').textContent = state.samples.length;
  $('samples').innerHTML = state.samples.map((sample,i) => `<div class="sample-row ${sample.id === state.selected ? 'active' : ''}"><button class="sample-button" data-sample="${sample.id}" title="${esc(sample.filename)}"><strong><span style="color:${colors[i%colors.length]}">●</span> ${esc(sample.filename)}</strong><small>${fmt(sample.events)} events · ${sample.channels.length} channels</small></button><button class="remove-sample" data-remove="${sample.id}" aria-label="Remove ${esc(sample.filename)}">×</button></div>`).join('');
  $('samples').querySelectorAll('[data-sample]').forEach(el => el.onclick = () => run(() => selectSample(el.dataset.sample)));
  $('samples').querySelectorAll('[data-remove]').forEach(el => el.onclick = () => run(async () => {
    await json(`/api/samples/${el.dataset.remove}`, undefined, 'DELETE');
    await refresh(); state.dirty = true;
  }));
}
function setupChannels(preserve=true) {
  const sample = current(); if (!sample) return;
  const url = new URL(window.location.href);
  url.searchParams.set('sample', sample.id); url.searchParams.delete('uploaded');
  window.history.replaceState(null, '', url);
  const previous = {x: $('x-channel').value, y: $('y-channel').value};
  for (const axis of ['x','y']) {
    $(`${axis}-channel`).innerHTML = sample.channels.map(ch => `<option value="${esc(ch.id)}">${esc(ch.label)}</option>`).join('');
    const fallback = axis === 'x' ? sample.channels.find(c => c.id === 'FSC-A') : sample.channels.find(c => c.id === 'SSC-A');
    $(`${axis}-channel`).value = preserve && sample.channels.some(c => c.id === previous[axis]) ? previous[axis] : fallback?.id || sample.channels[axis === 'x' ? 0 : Math.min(1,sample.channels.length-1)].id;
  }
  $('sample-title').textContent = sample.filename;
  $('source-note').textContent = `${sample.origin}  ·  FCS ${sample.fcs_version || 'unknown'}  ·  SHA-256 ${sample.sha256.slice(0,16)}…`;
  const fcsOption = $('compensation').querySelector('[value="fcs"]');
  fcsOption.textContent = sample.compensation_available ? 'Embedded FCS spillover' : 'Embedded FCS spillover · unavailable';
  // Never silently change the requested compensation when moving between samples.
}
function renderPopulationOptions() {
  const previous = $('compare-population').value;
  $('compare-population').innerHTML = `<option value="root">All events</option>` + state.gates.map(g => `<option value="${esc(g.name)}">${esc(g.name)}</option>`).join('');
  $('compare-population').value = state.gates.some(g => g.name === previous) ? previous : 'root';
  $('gate-count').textContent = state.gates.length;
}
async function refresh(options = {}) {
  const data = await json('/api/state');
  const oldIds = new Set(state.samples.map(s => s.id));
  state.samples = data.samples; state.gates = data.gates;
  $('fk-version').textContent = data.flowkit_version;
  state.samples.forEach(s => {if (!oldIds.has(s.id)) state.compareIds.add(s.id);});
  if (!state.samples.some(x => x.id === state.selected)) state.selected = state.samples[0]?.id || null;
  if (state.population !== 'root' && !state.gates.some(g => g.name === state.population)) state.population = 'root';
  $('empty').hidden = !!state.selected; $('loaded').hidden = !state.selected;
  document.body.classList.toggle('has-samples', !!state.selected);
  renderSamples(); renderPopulationOptions();
  if (state.selected) {setupChannels(options.preserveChannels !== false); await updateView();}
}
async function selectSample(id) {
  state.selected = id; renderSamples(); setupChannels(); resetSelection(); await updateView();
}
function baseLayout() {
  return {font:{family:'-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif',size:11,color:'#77718b'},
    paper_bgcolor:'#fff',plot_bgcolor:'#fff',margin:{l:72,r:27,t:15,b:63},showlegend:false,
    newselection:{line:{color:'#4200ac',width:2}},activeselection:{fillcolor:'rgba(66,0,172,0.07)'},
    hoverlabel:{bgcolor:'#fff',bordercolor:'#c4b0e7',font:{color:'#33266c'}},
    xaxis:{title:{text:labelAxis('x'),standoff:17,font:{size:11}},gridcolor:'#f0edf5',zerolinecolor:'#ded6eb',linecolor:'#e6e1ef',ticks:'outside',ticklen:3,automargin:true},
    yaxis:{title:{text:labelAxis('y'),standoff:12,font:{size:11}},gridcolor:'#f0edf5',zerolinecolor:'#ded6eb',linecolor:'#e6e1ef',ticks:'outside',ticklen:3,automargin:true}};
}
function density(x,y) {
  if (!x.length) return [];
  let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
  for(let i=0;i<x.length;i++){xmin=Math.min(xmin,x[i]);xmax=Math.max(xmax,x[i]);ymin=Math.min(ymin,y[i]);ymax=Math.max(ymax,y[i]);}
  const sx=xmax-xmin||1,sy=ymax-ymin||1, bins=new Map();
  const keys=x.map((v,i)=>`${Math.floor((v-xmin)/sx*90)},${Math.floor((y[i]-ymin)/sy*90)}`);
  for(const k of keys) bins.set(k,(bins.get(k)||0)+1);
  return keys.map(k=>Math.log1p(bins.get(k)));
}
function sameAxis(a,b) {return a.channel === b.channel && ['kind','t','m','w','a'].every(k=>a.transform[k] === b.transform[k]);}
function gateShapes(view) {
  const spec=viewSpec(), shapes=[], annotations=[];
  if (!view.x.length) return {shapes,annotations};
  let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
  for(let i=0;i<view.x.length;i++){xmin=Math.min(xmin,view.x[i]);xmax=Math.max(xmax,view.x[i]);ymin=Math.min(ymin,view.y[i]);ymax=Math.max(ymax,view.y[i]);}
  const dx=(xmax-xmin||1)*.08,dy=(ymax-ymin||1)*.08;
  for(const gate of state.gates) {
    if(gate.parent!==state.population || gate.compensation!==spec.compensation || !sameAxis(gate.x,spec.x) || !sameAxis(gate.y,spec.y)) continue;
    const common={line:{color:'#6fc0a9',width:2.2},fillcolor:'rgba(111,192,169,0.045)',layer:'above'};
    let ax,ay;
    if(gate.kind==='rectangle') {
      const [a,b,c,d]=gate.bounds, x0=a??xmin-dx,x1=b??xmax+dx,y0=c??ymin-dy,y1=d??ymax+dy;
      shapes.push({type:'rect',x0,x1,y0,y1,...common}); ax=x0;ay=y1;
    }else{const p=gate.vertices;shapes.push({type:'path',path:p.map((v,i)=>`${i?'L':'M'} ${v[0]},${v[1]}`).join(' ')+' Z',...common});ax=p[0][0];ay=p[0][1];}
    annotations.push({x:ax,y:ay,text:esc(gate.name),showarrow:false,xanchor:'left',yanchor:'bottom',font:{size:10,color:'#4200ac'},bgcolor:'#ffffffdd'});
  }
  return {shapes,annotations};
}
async function renderPlot(view) {
  const layout = {...baseLayout(),...gateShapes(view),dragmode:state.tool,selectionrevision:Date.now()};
  if (!view.display_count) layout.annotations=[{xref:'paper',yref:'paper',x:.5,y:.5,text:'No finite events in this population',showarrow:false,font:{size:13,color:'#7d8e83'}}];
  await Plotly.react('scatter',[{type:'scattergl',mode:'markers',x:view.x,y:view.y,customdata:view.event_indices,
    marker:{size:view.display_count>12000?2.5:3.5,opacity:.8,color:density(view.x,view.y),colorscale:[[0,'#d7ece5'],[.3,'#6fc0a9'],[.65,'#a88ad5'],[1,'#4200ac']],showscale:false},
    selected:{marker:{opacity:1}},unselected:{marker:{opacity:.3}},hovertemplate:'X: %{x:.4g}<br>Y: %{y:.4g}<br>Event index: %{customdata}<extra></extra>'}],layout,
    {responsive:true,displaylogo:false,displayModeBar:'hover',modeBarButtonsToRemove:['select2d','lasso2d','toImage'],scrollZoom:false});
  $('scatter').removeAllListeners('plotly_selected');
  $('scatter').on('plotly_selected',event=>{
    if(!event)return;
    if(event.lassoPoints){
      state.selection={kind:'polygon',vertices:event.lassoPoints.x.map((v,i)=>[v,event.lassoPoints.y[i]])};
      $('selection-note').textContent=`Polygon drawn with ${state.selection.vertices.length} vertices. Name your gate and save to count all events.`;
      document.querySelector('.bounds-grid').hidden=true;
    }else if(event.range?.x && event.range?.y){
      const xs=[...event.range.x].sort((a,b)=>a-b),ys=[...event.range.y].sort((a,b)=>a-b);
      state.selection={kind:'rectangle',bounds:[...xs,...ys]};
      ['x-min','x-max','y-min','y-max'].forEach((id,i)=>$(id).value=state.selection.bounds[i]);
      $('selection-note').textContent='Rectangle drawn. Name your gate and save to calculate its population.';
      document.querySelector('.bounds-grid').hidden=false;
    }
    if(state.selection){
      $('selection-ready').hidden=false;
      $('selection-kind').textContent=state.selection.kind==='polygon'?'Polygon ready':'Rectangle ready';
      if(!$('gate-name').value.trim())$('gate-name').value=nextGateName();
      $('gate-save-status').hidden=true;
    }
  });
  $('display-note').textContent=`${fmt(view.display_count)} displayed / ${fmt(view.population_count)} population events${view.nonfinite_count?` · ${fmt(view.nonfinite_count)} nonfinite pairs omitted`:''} · Gates use full data`;
}
function renderPopulations(view) {
  $('populations').innerHTML=view.populations.map(p=>`<div class="population-row ${p.name===state.population?'active':''}"><button class="population-item" data-pop="${esc(p.name)}" style="padding-left:${8+Math.min(p.depth,6)*10}px"><span class="pop-name">${p.depth?'↳':'◉'} ${esc(p.label)}</span><span class="pop-value">${fmt(p.count)}<small>${pct(p.percent_parent)} parent</small></span></button>${p.name!=='root'?`<button class="delete-gate" data-gate="${esc(p.name)}" aria-label="Delete ${esc(p.name)} and its children">×</button>`:''}</div>`).join('');
  $('populations').querySelectorAll('[data-pop]').forEach(el=>el.onclick=()=>run(async()=>{
    state.population=el.dataset.pop;
    const gate=state.gates.find(g=>g.name===state.population);
    if(gate){setAxis('x',gate.x);setAxis('y',gate.y);$('compensation').value=gate.compensation;}
    await updateView();
  }));
  $('populations').querySelectorAll('[data-gate]').forEach(el=>el.onclick=()=>run(async()=>{
    const name=el.dataset.gate;
    const children=state.gates.some(g=>g.parent===name);
    if(children && !confirm(`Delete “${name}” and all of its child populations?`))return;
    await json(`/api/gates/${encodeURIComponent(name)}`,undefined,'DELETE');state.dirty=true;await refresh();
  }));
}
async function updateView() {
  if(!current())return;
  resetSelection();
  if(state.tab==='compare'){await updateComparison();return;}
  const revision=++state.revision;
  $('scatter').style.opacity='.35';
  try {
    const view=await json('/api/view',viewSpec()); if(revision!==state.revision)return;
    state.view=view;
    $('total-events').textContent=fmt(view.total_count);$('population-count').textContent=fmt(view.population_count);
    $('population-label').textContent=state.population==='root'?'Current population':state.population;
    $('population-percent').textContent=`${pct(view.population_count/view.total_count*100)} of all events`;
    $('median-x').textContent=fmt(view.median_x);$('median-y').textContent=fmt(view.median_y);
    $('median-x-label').textContent=labelAxis('x');$('median-y-label').textContent=labelAxis('y');
    $('population-chip').textContent=state.population==='root'?'All events':state.population;
    $('parent-name').textContent=$('population-chip').textContent;
    $('plot-subtitle').textContent=`${$('compensation').value==='fcs'?'Embedded spillover compensated':'Uncompensated'} · ${state.tool==='lasso'?'drag a polygon, then release to finish':'drag on the plot to draw a gate'}`;
    renderPopulations(view);await renderPlot(view);
  } catch(error){
    state.view=null;
    ['total-events','population-count','population-percent','median-x','median-y'].forEach(id=>$(id).textContent='—');
    const depths={root:0}, populations=[{name:'root',label:'All events',depth:0,count:current().events,percent_parent:100}];
    for(const gate of state.gates){depths[gate.name]=(depths[gate.parent]||0)+1;populations.push({name:gate.name,label:gate.name,depth:depths[gate.name],count:null,percent_parent:null});}
    renderPopulations({populations});$('display-note').textContent='Analysis unavailable for the selected settings.';
    await Plotly.react('scatter',[],{...baseLayout(),annotations:[{xref:'paper',yref:'paper',x:.5,y:.5,text:'Analysis unavailable — see the message above',showarrow:false}]},{responsive:true,displaylogo:false});
    throw error;
  } finally{$('scatter').style.opacity='1';}
}
function renderCompareChecks() {
  $('comparison-select').innerHTML=state.samples.map((s,i)=>`<label title="${esc(s.filename)}"><input type="checkbox" data-compare="${s.id}" ${state.compareIds.has(s.id)?'checked':''}><span style="color:${colors[i%colors.length]}">●</span> ${esc(s.filename)}</label>`).join('');
  $('comparison-select').querySelectorAll('input').forEach(el=>el.onchange=()=>run(async()=>{
    if(el.checked)state.compareIds.add(el.dataset.compare);else state.compareIds.delete(el.dataset.compare);
    await updateComparison();
  }));
}
async function updateComparison() {
  renderCompareChecks();
  const spec=comparisonSpec();
  if(!spec.sample_ids.length){$('stats-body').innerHTML='<tr><td colspan="6">Select at least one sample.</td></tr>';await Plotly.react('histogram',[],baseLayout(),{responsive:true,displaylogo:false});return;}
  const data=await json('/api/compare',spec);
  $('stats-body').innerHTML=data.rows.map(row=>row.error?`<tr class="error-row"><td>${esc(row.sample)}</td><td colspan="5">${esc(row.error)}</td></tr>`:`<tr><td>${esc(row.sample)}</td><td>${fmt(row.count)}</td><td>${pct(row.percent_total)}</td><td>${pct(row.percent_parent)}</td><td>${fmt(row.median_x)}</td><td>${fmt(row.median_y)}</td></tr>`).join('');
  const traces=data.histograms.map(h=>({type:'scatter',mode:'lines',x:h.x,y:h.percent,name:h.sample,line:{width:2,color:colors[state.samples.findIndex(s=>s.id===h.sample_id)%colors.length]},fill:'tozeroy',fillcolor:colors[state.samples.findIndex(s=>s.id===h.sample_id)%colors.length]+'0d',hovertemplate:'%{x:.4g}<br>%{y:.2f}% of finite population events<extra>%{fullData.name}</extra>'}));
  const layout=baseLayout();layout.yaxis.title.text='Population events per bin (%)';layout.yaxis.rangemode='tozero';layout.margin.t=20;
  layout.xaxis.title.text=labelAxis(spec.histogram_axis);
  if(!traces.length)layout.annotations=[{xref:'paper',yref:'paper',x:.5,y:.5,text:'No compatible finite events to compare',showarrow:false}];
  await Plotly.react('histogram',traces,layout,{responsive:true,displaylogo:false});
}
async function switchTab(tab) {
  state.tab=tab;
  document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===tab));
  $('page-title').textContent=tab==='compare'?'Compare samples':'Explore & gate';
  $('explore-view').hidden=tab!=='explore';$('compare-view').hidden=tab!=='compare';
  if(current())await updateView();
}
async function upload(files) {
  if(!files.length)return;
  const form=new FormData();for(const file of files)form.append('files',file);
  const data=await json('/api/upload',form);state.dirty=true;
  if(data.samples.length){
    state.selected=data.samples[0].id;state.population='root';state.tab='explore';
    $('x-scale').value='linear';$('y-scale').value='linear';$('compensation').value='raw';
    document.querySelectorAll('[data-tab]').forEach(el=>el.classList.toggle('active',el.dataset.tab==='explore'));
    $('page-title').textContent='Explore & gate';$('explore-view').hidden=false;$('compare-view').hidden=true;
  }
  await refresh({preserveChannels:false});
  notice(data.errors.length?data.errors.map(x=>`${x.filename}: ${AurekaIntake.readableError(x.error)}`).join('\n'):`${data.samples.length} FCS file(s) ready. Choose your X and Y channels, draw a rectangle or polygon on the plot, then save your gate.`,!!data.errors.length);
}
function nextGateName(){let n=1;while(state.gates.some(g=>g.name===`Gate ${n}`))n++;return `Gate ${n}`;}
async function demo() {
  await json('/api/demo',{});await refresh();
  notice('Three synthetic demo samples loaded. These simulated signals are for trying plots and gates; they are not experimental measurements. Use Expression-A and Binding-A to explore the simulated fluorescence channels.');
}
function bind() {
  $('transform-fields').innerHTML=['x','y'].map(axis=>`<div class="parameter-row"><span>${axis.toUpperCase()}</span>${[['t',262144],['m',4.5],['w',.5],['a',0]].map(([key,value])=>`<label>${key.toUpperCase()}<input id="${axis}-${key}" type="number" step="any" value="${value}"></label>`).join('')}</div>`).join('');
  document.querySelectorAll('[data-tab]').forEach(el=>el.onclick=()=>run(()=>switchTab(el.dataset.tab)));
  AurekaIntake.bind({onFiles:files=>run(()=>upload(files),'Reading your FCS files…'),onError:message=>notice(message,true),isBusy:()=>state.busy>0});
  $('demo').onclick=()=>run(demo,'Generating synthetic demo samples…');$('empty-demo').onclick=()=>run(demo,'Generating synthetic demo samples…');
  $('dropzone').onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$('files').click();}};
  for(const axis of ['x','y']) {
    $(`${axis}-channel`).onchange=()=>run(async()=>{
      const channel=current().channels.find(c=>c.id===$(`${axis}-channel`).value);
      $(`${axis}-scale`).value=channel?.fluorescence?'logicle':'linear';notice('');await updateView();
    });
    $(`${axis}-scale`).onchange=()=>run(async()=>{notice('');await updateView();});
  }
  $('compensation').onchange=()=>run(async()=>{notice('');await updateView();});
  $('apply-transform').onclick=()=>run(async()=>{notice('');await updateView();});
  ['x-min','x-max','y-min','y-max'].forEach(id=>$(id).oninput=()=>state.selection=null);
  for(const [id,tool] of [['box-tool','select'],['lasso-tool','lasso'],['pan-tool','pan']]) {
    $(id).onclick=()=>{state.tool=tool;document.querySelectorAll('.plot-tools .tool').forEach(x=>{x.classList.toggle('active',x.id===id);x.setAttribute('aria-pressed',String(x.id===id));});resetSelection();if(state.view)Plotly.relayout('scatter',{dragmode:tool});};
  }
  $('clear-gate').onclick=()=>run(async()=>{resetSelection();if(state.view)await renderPlot(state.view);});
  $('save-gate').onclick=()=>run(async()=>{
    if(!state.view)throw new Error('Load a compatible sample and plot before saving a gate.');
    const v=viewSpec();let geometry=state.selection;
    if(!geometry || geometry.kind==='rectangle') {
      const bounds=['x-min','x-max','y-min','y-max'].map(id=>{if($(id).value==='')throw new Error('Draw a rectangle or provide all four boundaries.');return Number($(id).value);});
      geometry={kind:'rectangle',bounds};
    }
    const gate={name:$('gate-name').value.trim()||nextGateName(),parent:state.population,x:v.x,y:v.y,compensation:v.compensation,...geometry};
    const result=await json(`/api/gates?sample_id=${encodeURIComponent(state.selected)}`,gate);
    state.dirty=true;$('gate-name').value='';await refresh();notice(`“${result.name}” saved · ${fmt(result.count)} events in the selected sample. Select the population to inspect it or create a child gate.`);
    $('gate-save-status').hidden=false;$('gate-save-status').textContent=`✓ ${result.name} saved · ${fmt(result.count)} events`;
  });
  $('save-quadrants').onclick=()=>run(async()=>{
    if(!state.view)throw new Error('Load a compatible sample and plot first.');
    const e=$('expression-threshold').value,b=$('binding-threshold').value;
    if(e===''||b==='')throw new Error('Enter both thresholds from your expression and binding controls, in the current transformed scale.');
    const v=viewSpec();
    await json('/api/quadrants',{sample_id:state.selected,prefix:$('quadrant-prefix').value,parent:state.population,x:v.x,y:v.y,compensation:v.compensation,expression_threshold:Number(e),binding_threshold:Number(b)});
    state.dirty=true;await refresh();notice('Four quadrants and an Expression+ range gate saved. Compare Expression+ to inspect binding across all expression-positive events, or E+/B+ for the double-positive fraction.');
  });
  $('compare-population').onchange=()=>run(updateComparison);
  $('histogram-axis').onchange=()=>run(updateComparison);
  $('save-project').onclick=()=>run(async()=>{await download('/api/project',undefined,'aureka-flow-project.json');state.dirty=false;notice('Project JSON exported. It includes gate definitions, transform settings, FCS metadata and source hashes. Keep the original FCS files; event data are not embedded.');});
  $('restore').onclick=()=>$('project-file').click();
  $('project-file').onchange=()=>run(async()=>{
    const file=$('project-file').files[0];if(!file)return;
    if(file.size>5*1024*1024)throw new Error('Project JSON must be 5 MB or smaller.');
    if(state.gates.length&&!confirm('Replace the current gate strategy with this project? Save your current project first if needed.'))return;
    const project=JSON.parse(await file.text()),result=await json('/api/project',project);
    state.population='root';state.dirty=false;await refresh();
    notice(`${result.gates} gates restored.${result.missing_sources.length?' Re-upload these source FCS files (hashes do not match loaded samples): '+result.missing_sources.join(', '):' Source references match the loaded samples.'}`);
    $('project-file').value='';
  });
  $('metadata').onclick=()=>run(async()=>{$('source-content').textContent=JSON.stringify(await json(`/api/metadata/${state.selected}`),null,2);$('source-dialog').showModal();});
  $('close-dialog').onclick=()=>$('source-dialog').close();
  $('gatingml').onclick=()=>run(()=>download(`/api/gatingml?sample_id=${state.selected}`,undefined,'aureka-gates.xml'));
  $('export-events').onclick=()=>run(()=>download('/api/export/events',viewSpec(),'aureka-gated-events.csv'),'Exporting every event in this population…');
  $('export-stats').onclick=()=>run(()=>download('/api/export/stats',comparisonSpec(),'aureka-population-statistics.csv'));
  $('export-image').onclick=()=>run(async()=>{
    if(!state.view)throw new Error('There is no plot to export.');
    const graph=$('scatter'),sample=current(),view=state.view;
    const figure={data:graph.data,layout:{...graph.layout,
      title:{text:`Aureka Flow · ${esc(sample.filename)}<br><sup>Population: ${esc(state.population==='root'?'All events':state.population)} · ${$('compensation').value==='fcs'?'embedded spillover compensated':'uncompensated'} · ${esc(sample.origin)}</sup>`,font:{size:17,color:'#33266c'},x:.06,xanchor:'left'},
      margin:{...graph.layout.margin,t:100,b:110},
      annotations:[...(graph.layout.annotations||[]),{xref:'paper',yref:'paper',x:0,y:-.18,xanchor:'left',text:`${fmt(view.display_count)} displayed / ${fmt(view.population_count)} population events · SHA-256 ${sample.sha256.slice(0,16)}… · sampled visualization`,showarrow:false,font:{size:10,color:'#77718b'}}]}};
    await Plotly.downloadImage(figure,{format:'png',filename:'aureka-flow-'+state.population.replace(/[^\w-]+/g,'_'),width:1400,height:1000,scale:1.5});
  });
  window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
}
bind();run(async()=>{await refresh();if(startup.has('uploaded'))notice('Your FCS file is ready. Choose your channels, draw a gate on the plot, and save the population.');},'Opening local workspace…');
