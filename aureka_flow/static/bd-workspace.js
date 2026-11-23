/* Reviewed XML intake. Source XML is downloaded unchanged; analysis is explicit. */
let pendingXmlFile=null, xmlPreview=null;
function updateXmlReview() {
  const reconstruct=$('xml-mode').value==='reconstructed';
  $('xml-analysis-options').hidden=!reconstruct;
  $('apply-xml').textContent=reconstruct?'Apply reconstructed gates':'Preserve XML';
  $('apply-xml').disabled=!xmlPreview?.worksheets.length || (reconstruct &&
    (!$('xml-ack').checked || !xmlPreview.matches.length || !!xmlPreview.errors.length));
}
document.addEventListener('DOMContentLoaded',()=>{
  $('import-xml').onclick=()=>$('xml-file').click();
  $('xml-file').onchange=()=>run(async()=>{
    pendingXmlFile=$('xml-file').files[0];$('xml-file').value='';
    if(!pendingXmlFile)return;
    if(pendingXmlFile.size>5*1024*1024)throw new Error('Experiment XML must be 5 MB or smaller.');
    const form=new FormData();form.append('file',pendingXmlFile);
    xmlPreview=await json('/api/workspace/xml/preview',form);
    $('xml-summary').textContent=`${xmlPreview.experiment} · FACSDiva ${xmlPreview.version} · ${xmlPreview.samples.length} sample references · SHA-256 ${xmlPreview.sha256.slice(0,16)}…`;
    $('xml-matches').textContent=`${xmlPreview.matches.length} loaded FCS file(s) matched by exact filename; FCS hashes recorded.${xmlPreview.errors.length?' Resolve unmatched/conflicting samples before analysis: '+xmlPreview.errors.join(' '):' Unloaded XML samples are preserved; only matched FCS files are analyzed.'}`;
    $('xml-worksheet').innerHTML=xmlPreview.worksheets.map(w=>`<option value="${esc(w.id)}">${esc(w.name)} · ${w.gate_records} source gate records</option>`).join('');
    $('xml-details').textContent=xmlPreview.warnings.join('\n\n')+'\n\n'+xmlPreview.samples.map(s=>`${s.filename} · ${s.name} · ${s.instrument || 'instrument unspecified'}`).join('\n');
    $('xml-mode').value='preserve';$('xml-ack').checked=false;
    updateXmlReview();$('xml-dialog').showModal();
  },'Reading instrument gates and compensation…');
  for(const id of ['xml-mode','xml-ack'])$(id).onchange=updateXmlReview;
  for(const id of ['close-xml','cancel-xml'])$(id).onclick=()=>$('xml-dialog').close();
  $('apply-xml').onclick=()=>{
    $('xml-dialog').close();
    run(async()=>{
      const form=new FormData();form.append('file',pendingXmlFile);
      for(const [key,id] of [['worksheet','xml-worksheet'],['mode','xml-mode'],['compensation','xml-compensation']])form.append(key,$(id).value);
      form.append('acknowledged',String($('xml-ack').checked));
      const result=await json('/api/workspace/xml',form);
      state.population='root';state.dirty=true;resetSelection();await refresh();
      if(result.mode==='reconstructed')$('compensation').value=$('xml-compensation').value;
      if(current())await updateView();
      notice(result.mode==='reconstructed'?`${result.gates} reconstructed gates applied to ${result.matched_samples} hash-bound sample(s). Compare these counts with FACSDiva before relying on them. Original XML preserved.`:'Original XML preserved. No instrument gates were applied; the gate strategy is empty. Save a project to keep the XML and settings.');
      pendingXmlFile=null;
    },'Preserving XML and calculating full-event populations…');
  };
  $('download-source-xml').onclick=()=>run(()=>download('/api/workspace/xml',undefined,'source-workspace.xml'));
});
