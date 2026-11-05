/* Browser UI. Only geometry is sent to FlowKit; displayed event indices never define gates. */
const $ = id => document.getElementById(id);
const colors = ['#4200ac', '#6fc0a9', '#9270cf', '#3d328f', '#a6d7c8', '#b49ae2'];
const startup = new URLSearchParams(window.location.search);
const state = {samples: [], gates: [], selected: startup.get('sample'), population: 'root', tab: 'explore',
  selection: null, tool: 'select', view: null, revision: 0, compareIds: new Set(), busy: 0, dirty: false};
let gateDrawing, drawingInfo=null;
const fmt = v => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: 3});
const pct = v => v == null ? '—' : `${Number(v).toFixed(2)}%`;
const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function notice(message, error=false) {
  $('notice').textContent = message; $('notice').classList.toggle('error', error); $('notice').hidden = !message;
}
async function api(url, data, method) {
  const options = {method: method || (data === undefined ? 'GET' : 'POST'),credentials:'same-origin'};
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
    state.busy--; if (!state.busy) {$('busy').hidden = true; document.querySelectorAll('button, #loaded select').forEach(x => x.disabled = false);updatePlotControls();updateDrawingControls();}
  }
}
async function download(url, data, filename) {
  const response = await api(url, data);
  const blob = await response.blob(), link = document.createElement('a'), href = URL.createObjectURL(blob);
  link.href = href; link.download = filename; document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(href), 30000);
}
const current = () => state.samples.find(x => x.id === state.selected);
const isHistogram = () => $('plot-type').value === 'histogram';
const backgateContext = () => state.capabilities?.backgating ? $('backgate-context').value : '';
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
function viewSpec() {
  const spec={sample_id: state.selected, x: axisSpec('x'), y: isHistogram()?null:axisSpec('y'), compensation: $('compensation').value, population: state.population, max_points: 25000};
  if(isHistogram())Object.assign(spec,{plot_type:'histogram',histogram_bins:Number($('histogram-bins').value)});
  if(backgateContext())spec.context_population=backgateContext();
  return spec;
}
function comparisonSpec() {
  const spec={sample_ids: state.samples.filter(x => state.compareIds.has(x.id)).map(x => x.id),
    x: axisSpec('x'), y: isHistogram()?null:axisSpec('y'), compensation: $('compensation').value, population: $('compare-population').value || 'root',histogram_axis: isHistogram()?'x':$('histogram-axis').value};
  if(state.capabilities?.histogram_overlays)spec.histogram_bins=Number($('overlay-bins').value);
  return spec;
}
function updateBackgateControl() {
  const previous=$('backgate-context').value,ancestors=[];
  let gate=state.gates.find(g=>g.name===state.population);
  while(gate){ancestors.push(gate.parent);gate=state.gates.find(g=>g.name===gate.parent);}
  $('backgate-context').innerHTML='<option value="">Off · draw gates</option>'+ancestors.map(name=>`<option value="${esc(name)}">${esc(name==='root'?'All events':name)}</option>`).join('');
  $('backgate-context').value=ancestors.includes(previous)?previous:'';
  $('backgate-context').disabled=!!state.busy||!ancestors.length;
}
function drawingHint() {
  if(backgateContext())return 'Backgating preview · turn Off to draw new gates in this population.';
  return state.tool==='pan'?'Drag to pan. Choose a gate tool to draw.':isHistogram()?'Drag left to right across an X range, then Save population.':state.tool==='lasso'?'Click polygon corners, then Finish polygon or press Enter. You can also trace by dragging.':'Drag a rectangle on the plot, then Save population.';
}
function updatePlotControls() {
  const hist=isHistogram(),supported=!!state.capabilities?.range_gates;
  updateBackgateControl();
  const context=backgateContext();
  const option=$('plot-type').querySelector('[value="histogram"]');
  option.disabled=!supported;option.textContent=supported?'Histogram':'Histogram · restart server to enable';
  document.body.classList.toggle('histogram-mode',hist);
  document.body.classList.toggle('backgating-mode',!!context);
  $('backgate-settings').hidden=!state.capabilities?.backgating||state.tab!=='explore';
  $('backgate-help').textContent=context?'Purple: selected population. Gray: ancestor. Counts and downloads still use the selected population.':'Select a saved population to inspect it against an ancestor on any channels.';
  $('overlay-settings').hidden=!state.capabilities?.histogram_overlays;
  $('table-scope-control').hidden=!state.capabilities?.population_table;
  document.querySelectorAll('.histogram-setting').forEach(el=>el.hidden=!hist||state.tab!=='explore');
  ['y-channel-control','y-scale-control','xy-divider','compensation-divider','swap-axes','quadrants-panel','y-min-control','y-max-control','comparison-axis-control','lasso-tool'].forEach(id=>$(id).hidden=hist);
  document.querySelector('#transform-fields .parameter-row:last-child').hidden=hist;
  $('box-tool').querySelector('span').textContent=hist?'Range':'Rectangle';
  $('box-tool').title=hist?'Drag horizontally to select a channel range':'Drag to draw a rectangular gate';
  $('plot-mode-help').textContent=state.tab==='compare'?'Full-event distributions with shared bin edges. Choose normalization below.':context?'Backgating preview · turn Off below to resume drawing.':hist?'All finite population events · drag an X range to gate.':'Choose any FCS channel on either axis.';
  $('y-metric-title').textContent=hist?'Finite · X channel':'Median · Y channel';
  if(hist&&state.tool==='lasso')state.tool='select';
  for(const [id,tool] of [['box-tool','select'],['lasso-tool','lasso'],['pan-tool','pan']]){
    const active=context?tool==='pan':state.tool===tool;
    $(id).classList.toggle('active',active);$(id).setAttribute('aria-pressed',String(active));
    if(context&&tool!=='pan')$(id).disabled=true;
  }
  $('save-gate').disabled=!!state.busy||!!context;
  $('save-quadrants').disabled=!!state.busy||!!context;
  gateDrawing?.setTool(context?'pan':hist&&state.tool==='select'?'range':state.tool);
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
  gateDrawing?.clear();
  ['x-min','x-max','y-min','y-max','expression-threshold','binding-threshold'].forEach(id => $(id).value = '');
  $('selection-note').textContent = drawingHint();
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
  if(sample.channels.length===1&&state.capabilities?.range_gates)$('plot-type').value='histogram';
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
  state.workspace=data.workspace;state.capabilities=data.capabilities;
  if(isHistogram()&&!data.capabilities?.range_gates)$('plot-type').value='density';
  updatePlotControls();
  $('app-version').textContent='v'+data.version;
  const hosted=data.workspace?.mode==='server';
  $('workspace-mode').textContent=hosted?'SERVER WORKSPACE':'LOCAL WORKSPACE';
  $('connection-label').textContent='Private browser session';
  $('storage-note').textContent=hosted?`Files are uploaded to this server for your session. Download results before ${Math.round(data.workspace.idle_timeout_seconds/60)} minutes of inactivity.`:'Analysis runs on this computer. Each browser has its own workspace. Download results before leaving.';
  $('clear-workspace').hidden=!data.workspace;
  $('download-analysis').hidden=!data.workspace;
  if(data.limits){window.AurekaIntake.limits=data.limits;document.querySelector('.intake-copy small').textContent=`One or multiple .fcs files · up to ${Math.round(data.limits.file_bytes/1024**2)} MB each · ${hosted?'server':'local'} analysis`;}
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
    yaxis:{title:{text:isHistogram()?($('histogram-normalization').value==='percent'?(backgateContext()?'Ancestor events per bin (%)':'Population events per bin (%)'):'Event count'):labelAxis('y'),standoff:12,font:{size:11}},gridcolor:'#f0edf5',zerolinecolor:'#ded6eb',linecolor:'#e6e1ef',ticks:'outside',ticklen:3,automargin:true}};
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
function sameAxis(a,b) {return !!a&&!!b&&a.channel === b.channel && ['kind','t','m','w','a'].every(k=>a.transform[k] === b.transform[k]);}
function gateShapes(view) {
  const spec=viewSpec(), shapes=[], annotations=[];
  if (!view.display_count||view.context) return {shapes,annotations};
  const hist=isHistogram();
  let xmin=hist?view.histogram.edges[0]:Infinity,xmax=hist?view.histogram.edges.at(-1):-Infinity,ymin=Infinity,ymax=-Infinity;
  if(!hist)for(let i=0;i<view.x.length;i++){xmin=Math.min(xmin,view.x[i]);xmax=Math.max(xmax,view.x[i]);ymin=Math.min(ymin,view.y[i]);ymax=Math.max(ymax,view.y[i]);}
  const dx=(xmax-xmin||1)*.08,dy=(ymax-ymin||1)*.08;
  for(const gate of state.gates) {
    if(gate.parent!==state.population || gate.compensation!==spec.compensation || !sameAxis(gate.x,spec.x)) continue;
    const range=gate.kind==='range'||(gate.kind==='rectangle'&&gate.bounds[2]===null&&gate.bounds[3]===null);
    if(hist&&!range || !hist&&!range&&!sameAxis(gate.y,spec.y))continue;
    const common={line:{color:'#6fc0a9',width:2.2},fillcolor:'rgba(111,192,169,0.045)',layer:'above'};
    let ax,ay;
    if(range){
      const [a,b]=gate.bounds;
      shapes.push({type:'rect',x0:a??xmin-dx,x1:b??xmax+dx,yref:'paper',y0:0,y1:1,...common});
      annotations.push({x:a??xmin,yref:'paper',y:.98,text:esc(gate.name),showarrow:false,xanchor:'left',yanchor:'top',font:{size:10,color:'#4200ac'},bgcolor:'#ffffffdd'});
      continue;
    }else if(gate.kind==='rectangle') {
      const [a,b,c,d]=gate.bounds, x0=a??xmin-dx,x1=b??xmax+dx,y0=c??ymin-dy,y1=d??ymax+dy;
      shapes.push({type:'rect',x0,x1,y0,y1,...common}); ax=x0;ay=y1;
    }else{const p=gate.vertices;shapes.push({type:'path',path:p.map((v,i)=>`${i?'L':'M'} ${v[0]},${v[1]}`).join(' ')+' Z',...common});ax=p[0][0];ay=p[0][1];}
    annotations.push({x:ax,y:ay,text:esc(gate.name),showarrow:false,xanchor:'left',yanchor:'bottom',font:{size:10,color:'#4200ac'},bgcolor:'#ffffffdd'});
  }
  return {shapes,annotations};
}
async function renderPlot(view) {
  const layout = {...baseLayout(),...gateShapes(view),dragmode:backgateContext()||state.tool==='pan'?'pan':false};
  if (!view.display_count) layout.annotations=[{xref:'paper',yref:'paper',x:.5,y:.5,text:'No finite events in this population',showarrow:false,font:{size:13,color:'#7d8e83'}}];
  let trace,background;
  if(isHistogram()){
    const h=view.histogram,percent=$('histogram-normalization').value==='percent';
    layout.yaxis.rangemode='tozero';layout.bargap=0;layout.xaxis.range=[h.edges[0],h.edges.at(-1)];
    trace={type:'bar',x:h.centers,width:h.widths,y:percent?h.percent:h.counts,customdata:h.counts,
      marker:{color:'rgba(66,0,172,.72)',line:{color:'#4200ac',width:.35}},
      hovertemplate:percent?'X: %{x:.4g}<br>%{y:.2f}% · %{customdata} events<extra></extra>':'X: %{x:.4g}<br>%{y:,} events<extra></extra>'};
    if(view.context){
      background={...trace,y:percent?view.context.histogram.percent:view.context.histogram.counts,
        customdata:view.context.histogram.counts,marker:{color:'rgba(145,140,157,.35)',line:{color:'#aaa4b5',width:.3}}};
      layout.barmode='overlay';
    }
  }else{
    trace={type:'scattergl',mode:'markers',x:view.x,y:view.y,customdata:view.event_indices,
      marker:{size:view.display_count>12000?2.5:3.5,opacity:.8,color:!view.context&&$('plot-type').value==='density'?density(view.x,view.y):'#4200ac',colorscale:[[0,'#d7ece5'],[.3,'#6fc0a9'],[.65,'#a88ad5'],[1,'#4200ac']],showscale:false},
      selected:{marker:{opacity:1}},unselected:{marker:{opacity:.3}},hovertemplate:'X: %{x:.4g}<br>Y: %{y:.4g}<br>Event index: %{customdata}<extra></extra>'};
    if(view.context)background={...trace,x:view.context.x,y:view.context.y,customdata:view.context.event_indices,
      marker:{size:2.5,opacity:.3,color:'#aaa4b5'}};
  }
  const traces=[trace];
  if(background){
    const name=view.context.population==='root'?'All events':view.context.population;
    background.name=`${name} · ${fmt(view.context.population_count)} events`;
    trace.name=`${state.population} · ${fmt(view.population_count)} events`;
    traces.unshift(background);layout.showlegend=true;layout.margin.t=55;
    layout.legend={orientation:'h',x:0,y:1.14,font:{size:10}};
  }
  await Plotly.react('scatter',traces,layout,
    {responsive:true,displaylogo:false,displayModeBar:'hover',modeBarButtonsToRemove:['select2d','lasso2d','zoom2d','pan2d','toImage'],scrollZoom:false});
  $('scatter').removeAllListeners('plotly_relayout');
  $('scatter').on('plotly_relayout',()=>gateDrawing.sync());
  gateDrawing.sync();
  $('display-note').textContent=isHistogram()?`${fmt(view.display_count)} finite / ${fmt(view.population_count)} population events · ${$('histogram-bins').value} bins · Full-event histogram${view.nonfinite_count?` · ${fmt(view.nonfinite_count)} nonfinite values omitted`:''}`:`${fmt(view.display_count)} displayed / ${fmt(view.population_count)} population events${view.nonfinite_count?` · ${fmt(view.nonfinite_count)} nonfinite pairs omitted`:''} · Gates use full data`;
  if(view.context)$('display-note').textContent+=` · Gray ancestor: ${fmt(view.context.population_count)} events${isHistogram()?($('histogram-normalization').value==='percent'?' · % denominator: finite ancestor events':''):` (${fmt(view.context.display_count)} displayed)`}`;
}
function renderPopulations(view) {
  $('populations').innerHTML=view.populations.map(p=>`<div class="population-row ${p.name===state.population?'active':''}"><button class="population-item" data-pop="${esc(p.name)}" style="padding-left:${8+Math.min(p.depth,6)*10}px"><span class="pop-name">${p.depth?'↳':'◉'} ${esc(p.label)}</span><span class="pop-value">${fmt(p.count)}<small>${pct(p.percent_parent)} parent</small></span></button>${p.name!=='root'?`<button class="delete-gate" data-gate="${esc(p.name)}" aria-label="Delete ${esc(p.name)} and its children">×</button>`:''}</div>`).join('');
  $('populations').querySelectorAll('[data-pop]').forEach(el=>el.onclick=()=>run(async()=>{
    state.population=el.dataset.pop;
    const gate=state.gates.find(g=>g.name===state.population);
    if(gate){
      if(gate.kind==='range'){$('plot-type').value='histogram';setAxis('x',gate.x);}
      else if(!isHistogram()){setAxis('x',gate.x);setAxis('y',gate.y);}
      $('compensation').value=gate.compensation;
    }
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
  updatePlotControls();
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
    $('median-x').textContent=fmt(view.median_x);$('median-y').textContent=fmt(isHistogram()?view.histogram.finite_count:view.median_y);
    $('median-x-label').textContent=labelAxis('x');$('median-y-label').textContent=isHistogram()?'Events included in the histogram':labelAxis('y');
    $('population-chip').textContent=state.population==='root'?'All events':state.population;
    $('plot-action-title').textContent=view.context?'Backgate population':'Draw your gates';
    $('parent-name').textContent=$('population-chip').textContent;
    $('plot-subtitle').textContent=`${$('compensation').value==='fcs'?'Embedded spillover compensated':'Uncompensated'} · ${drawingHint()}`;
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
function renderStats(rows) {
  $('stats-body').innerHTML=rows.map(row=>row.error?`<tr class="error-row"><td>${esc(row.sample)}</td><td colspan="6">${esc(row.error)}</td></tr>`:`<tr><td>${esc(row.sample)}</td><td title="${esc(row.path||row.population)}">${esc(row.population==='root'?'All events':row.population)}${row.parent?`<small class="table-parent">Parent: ${esc(row.parent==='root'?'All events':row.parent)}</small>`:''}</td><td>${fmt(row.count)}</td><td>${pct(row.percent_total)}</td><td>${pct(row.percent_parent)}</td><td>${fmt(row.median_x)}</td><td>${fmt(row.median_y)}</td></tr>`).join('');
  $('stats-caption').textContent=`${rows.length} rows · all gated events · medians use the selected channel transforms`;
}
async function updateComparison() {
  renderCompareChecks();
  const spec=comparisonSpec();
  if(!spec.sample_ids.length){$('stats-body').innerHTML='<tr><td colspan="7">Select at least one sample.</td></tr>';await Plotly.react('histogram',[],baseLayout(),{responsive:true,displaylogo:false});return;}
  const data=await json('/api/compare',spec);
  const all=state.capabilities?.population_table&&$('table-scope').value==='all';
  renderStats(all?(await json('/api/population-table',spec)).rows:data.rows);
  const normalization=state.capabilities?.histogram_overlays?$('overlay-normalization').value:'percent';
  const help={percent:'Area normalization: each nonempty sample sums to 100% of its finite population events.',counts:'Event counts: shows yield per bin; acquisition size and recovery can differ between samples.',modal:'Modal normalization: each nonempty sample peaks at 100%; area and population yield are not preserved.'};
  const titles={percent:'Population events per bin (%)',counts:'Event count',modal:'Peak-normalized bin height (%)'};
  $('overlay-help').textContent=help[normalization];
  $('comparison-note').textContent=`${spec.histogram_bins||100} shared bins · ${spec.population==='root'?'All events':spec.population} · full-event distributions`;
  const traces=data.histograms.map(h=>{
    const color=colors[state.samples.findIndex(s=>s.id===h.sample_id)%colors.length];
    return {type:'scatter',mode:'lines',x:h.x,y:h[normalization],name:h.sample+(h.finite_count===undefined?'':` · ${fmt(h.finite_count)} finite`),
      line:{width:2,color,shape:'hvh'},fill:$('overlay-style').value==='filled'?'tozeroy':'none',fillcolor:color+'15',
      hovertemplate:normalization==='counts'?'%{x:.4g}<br>%{y:,} events<extra>%{fullData.name}</extra>':`%{x:.4g}<br>%{y:.2f}%${normalization==='modal'?' of peak':' of finite population events'}<extra>%{fullData.name}</extra>`};
  });
  const layout=baseLayout();layout.yaxis.title.text=titles[normalization];layout.yaxis.rangemode='tozero';layout.margin.t=70;
  layout.showlegend=true;layout.legend={orientation:'h',x:0,y:1.2,font:{size:10}};
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
function updateDrawingControls() {
  if(!$('drawing-controls'))return;
  $('drawing-controls').hidden=!drawingInfo;
  $('quick-gate-editor').hidden=!drawingInfo?.ready;
  $('finish-polygon').hidden=drawingInfo?.kind!=='polygon'||drawingInfo?.ready;
  $('finish-polygon').disabled=state.busy>0||(drawingInfo?.vertices||0)<3;
  $('undo-vertex').hidden=drawingInfo?.kind!=='polygon';
  $('quick-save-gate').disabled=state.busy>0||!drawingInfo?.ready;
  if(drawingInfo)$('drawing-progress').textContent=drawingInfo.ready?'Gate ready · name and save below':`${drawingInfo.vertices} corners · click more, or Finish polygon`;
}
function acceptDrawing(geometry) {
  state.selection=geometry;
  const polygon=geometry.kind==='polygon',range=geometry.kind==='range';
  document.querySelector('.bounds-grid').hidden=polygon;
  if(!polygon)['x-min','x-max','y-min','y-max'].forEach((id,i)=>$(id).value=geometry.bounds[i]??'');
  $('selection-note').textContent=polygon?`Polygon ready with ${geometry.vertices.length} vertices.`:range?'X range ready. Save to count every event in the range; the Y axis does not define membership.':'Rectangle ready. Save to count every event in the population.';
  $('selection-ready').hidden=false;
  $('selection-kind').textContent=polygon?'Polygon ready':range?'Range ready':'Rectangle ready';
  if(!$('gate-name').value.trim())$('gate-name').value=nextGateName();
  $('quick-gate-name').value=$('gate-name').value;
  $('quick-parent').textContent='Parent: '+(state.population==='root'?'All events':state.population);
  $('gate-save-status').hidden=true;
}
async function saveGate() {
  if(!state.view)throw new Error('Load a compatible sample and plot before saving a gate.');
  if(backgateContext())throw new Error('Turn backgating Off to draw or save a new gate.');
  const v=viewSpec();let geometry=state.selection;
  if(!geometry||geometry.kind==='rectangle'||geometry.kind==='range') {
    const bounds=['x-min','x-max','y-min','y-max'].map((id,i)=>{
      if(isHistogram()&&i>1)return null;
      if($(id).value==='')return null;
      const value=Number($(id).value);if(!Number.isFinite(value))throw new Error('Gate boundaries must be finite numbers.');return value;
    });
    if(bounds.every(v=>v===null))throw new Error('Draw a gate or enter at least one boundary. Blank boundaries are unbounded.');
    geometry={kind:isHistogram()?'range':'rectangle',bounds};
  }
  const gate={name:$('gate-name').value.trim()||nextGateName(),parent:state.population,x:v.x,y:v.y,compensation:v.compensation,...geometry};
  const result=await json(`/api/gates?sample_id=${encodeURIComponent(state.selected)}`,gate);
  state.dirty=true;state.population=result.name;$('gate-name').value='';$('quick-gate-name').value='';await refresh();
  notice(`“${result.name}” saved and selected · ${fmt(result.count)} events. Download this population's analysis, draw a child gate, or select All events to begin another gate.`);
  $('gate-save-status').hidden=false;$('gate-save-status').textContent=`✓ ${result.name} saved · ${fmt(result.count)} events`;
}
function bind() {
  gateDrawing=AurekaGateDrawing.create({plot:$('scatter'),svg:$('gate-overlay'),onComplete:acceptDrawing,
    onChange:info=>{drawingInfo=info;if(!info?.ready)state.selection=null;updateDrawingControls();},
    onError:message=>notice(message,true),canDraw:()=>!state.busy&&!!state.view&&state.tab==='explore'&&!backgateContext()});
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
  $('plot-type').onchange=()=>run(async()=>{notice('');await updateView();});
  $('histogram-normalization').onchange=()=>run(updateView);
  $('histogram-bins').onchange=()=>run(updateView);
  $('backgate-context').onchange=()=>run(updateView);
  ['overlay-normalization','overlay-bins','overlay-style','table-scope'].forEach(id=>$(id).onchange=()=>run(updateComparison));
  $('swap-axes').onclick=()=>run(async()=>{
    const x=axisSpec('x'),y=axisSpec('y');setAxis('x',y);setAxis('y',x);await updateView();
  });
  $('compensation').onchange=()=>run(async()=>{notice('');await updateView();});
  $('apply-transform').onclick=()=>run(async()=>{notice('');await updateView();});
  ['x-min','x-max','y-min','y-max'].forEach(id=>$(id).oninput=()=>{state.selection=null;gateDrawing.clear();});
  $('gate-name').oninput=()=>{$('quick-gate-name').value=$('gate-name').value;};
  $('quick-gate-name').oninput=()=>{$('gate-name').value=$('quick-gate-name').value;};
  for(const [id,tool] of [['box-tool','select'],['lasso-tool','lasso'],['pan-tool','pan']]) {
    $(id).onclick=()=>{state.tool=tool;updatePlotControls();resetSelection();if(state.view){Plotly.relayout('scatter',{dragmode:tool==='pan'?'pan':false});$('plot-subtitle').textContent=drawingHint();}};
  }
  $('finish-polygon').onclick=()=>gateDrawing.finish();
  $('undo-vertex').onclick=()=>gateDrawing.undo();
  $('cancel-drawing').onclick=()=>resetSelection();
  $('clear-gate').onclick=()=>run(async()=>{resetSelection();if(state.view)await renderPlot(state.view);});
  $('save-gate').onclick=()=>run(saveGate);
  $('quick-save-gate').onclick=()=>run(saveGate);
  $('download-analysis').onclick=()=>run(async()=>{
    if(!current())throw new Error('Upload an FCS sample first.');
    const spec=state.tab==='compare'?comparisonSpec():{sample_ids:[state.selected],x:axisSpec('x'),y:isHistogram()?null:axisSpec('y'),compensation:$('compensation').value,population:state.population,histogram_axis:isHistogram()?'x':'y'};
    if(!spec.sample_ids.length)throw new Error('Select at least one sample to download.');
    const all=!!state.capabilities?.population_table&&state.tab==='compare'&&$('table-scope').value==='all';
    await download('/api/export/bundle?include_events='+$('include-events').checked+'&include_population_table='+all,spec,'aureka-analysis.zip');
    state.dirty=false;notice('Analysis ZIP downloaded: population statistics, project, GatingML, source hashes'+(all?', all-populations table':'')+($('include-events').checked?' and every gated event.':'.'));
  },'Preparing your analysis download…');
  $('clear-workspace').onclick=()=>run(async()=>{
    if(!confirm('Clear your loaded samples and gates? Download your analysis first if you need to keep it.'))return;
    await json('/api/session',undefined,'DELETE');state.selected=null;state.population='root';state.dirty=false;resetSelection();await refresh();notice('Your workspace is empty. Other users are unaffected.');
  });
  $('save-quadrants').onclick=()=>run(async()=>{
    if(!state.view)throw new Error('Load a compatible sample and plot first.');
    if(isHistogram())throw new Error('Choose a dot plot and two channels to create expression × binding quadrants.');
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
  $('export-stats').onclick=()=>run(()=>{
    const all=!!state.capabilities?.population_table&&$('table-scope').value==='all';
    return download(all?'/api/export/population-table':'/api/export/stats',comparisonSpec(),all?'aureka-all-populations.csv':'aureka-population-statistics.csv');
  });
  $('export-overlay').onclick=()=>run(async()=>{
    const graph=$('histogram');if(!graph.data?.length)throw new Error('Choose compatible samples to export an overlay.');
    const spec=comparisonSpec(),normalization=$('overlay-normalization').value;
    const synthetic=state.samples.filter(s=>spec.sample_ids.includes(s.id)).every(s=>s.origin?.startsWith('Synthetic demo'));
    const figure={data:graph.data,layout:{...graph.layout,margin:{...graph.layout.margin,t:150,b:130},legend:{...graph.layout.legend,y:1.08},
      title:{text:`Aureka Flow · ${esc(spec.population==='root'?'All events':spec.population)}<br><sup>${spec.histogram_bins||100} common bins · ${normalization==='modal'?'peak = 100%':normalization==='counts'?'event counts':'area = 100% per sample'} · ${spec.compensation==='fcs'?'embedded spillover compensated':'uncompensated'}${synthetic?' · synthetic signals':''}</sup>`,x:.06,y:.97,xanchor:'left',font:{size:17,color:'#33266c'}},
      annotations:[{xref:'paper',yref:'paper',x:0,y:-.12,xanchor:'left',text:synthetic?'Synthetic demo · simulated signals, not experimental data':'Full-event distributions · sources and gate settings available in the analysis ZIP',showarrow:false,font:{size:10,color:'#77718b'}}]}};
    await Plotly.downloadImage(figure,{format:'png',filename:'aureka-overlay',width:1500,height:1000,scale:1.5});
  });
  $('export-image').onclick=()=>run(async()=>{
    if(!state.view)throw new Error('There is no plot to export.');
    const graph=$('scatter'),sample=current(),view=state.view;
    const figure={data:graph.data,layout:{...graph.layout,
      title:{text:`Aureka Flow · ${esc(sample.filename)}<br><sup>Population: ${esc(state.population==='root'?'All events':state.population)} · ${$('compensation').value==='fcs'?'embedded spillover compensated':'uncompensated'} · ${esc(sample.origin)}</sup>`,font:{size:17,color:'#33266c'},x:.06,xanchor:'left'},
      margin:{...graph.layout.margin,t:100,b:110},
      annotations:[...(graph.layout.annotations||[]),{xref:'paper',yref:'paper',x:0,y:-.18,xanchor:'left',text:`${fmt(view.display_count)} ${isHistogram()?'finite':'displayed'} / ${fmt(view.population_count)} population events · SHA-256 ${sample.sha256.slice(0,16)}… · ${isHistogram()?'full-event histogram':'sampled visualization'}`,showarrow:false,font:{size:10,color:'#77718b'}}]}};
    await Plotly.downloadImage(figure,{format:'png',filename:'aureka-flow-'+state.population.replace(/[^\w-]+/g,'_'),width:1400,height:1000,scale:1.5});
  });
  window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
}
async function openPractice() {
  if(!state.samples.length)await demo();
  const sample=state.samples.find(s=>s.filename==='synthetic_binding.fcs'&&s.origin?.startsWith('Synthetic demo'));
  if(sample&&state.samples.every(s=>s.origin?.startsWith('Synthetic demo'))){
    state.selected=sample.id;state.population='root';renderSamples();setupChannels();
    const scale={kind:'logicle',t:262144,m:4.5,w:.5,a:0};
    setAxis('x',{channel:'Expression-A',transform:scale});setAxis('y',{channel:'Binding-A',transform:scale});
    $('compensation').value='raw';await updateView();
    $('quadrant-prefix').value='Practice split';$('expression-threshold').value=.45;$('binding-threshold').value=.38;
    notice('PRACTICE · synthetic FCS data, not experimental results.\n1. Rectangle: drag around a cluster, name it, then Save population below the plot.\n2. Polygon: click at least three corners, Finish polygon, then Save population.\n3. To draw a separate population, select All events first. To split into four groups, open Expression × binding quadrants (demo thresholds X=0.45, Y=0.38).');
  }else notice('Practice workspace opened with your existing samples and gates. Use Try synthetic demo data to add examples; your work has not been cleared.');
}
bind();run(async()=>{await refresh();if(startup.get('practice')==='1')await openPractice();else if(startup.has('uploaded'))notice('Your FCS file is ready. Choose your channels, draw a gate on the plot, and save the population.');},'Opening your workspace…');
