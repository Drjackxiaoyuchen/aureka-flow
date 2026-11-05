let reportUploading = false;
const reportStatus = document.getElementById('report-upload-status');
fetch('/api/state',{credentials:'same-origin'}).then(response=>response.json()).then(state=>{
  if(state.limits)window.AurekaIntake.limits=state.limits;
  const note=document.querySelector('.intake-copy small');
  if(note&&state.limits)note.textContent=`.fcs files · up to ${Math.round(state.limits.file_bytes/1024**2)} MB each · ${state.workspace?.mode==='server'?'uploaded to this server':'processed on this computer'}`;
}).catch(()=>{});
function reportMessage(message, error = false) {
  reportStatus.textContent = message; reportStatus.classList.toggle('error', error); reportStatus.hidden = false;
}
AurekaIntake.bind({
  isBusy: () => reportUploading,
  onError: message => reportMessage(message, true),
  onFiles: async files => {
    reportUploading = true;
    document.querySelectorAll('[data-upload-trigger]').forEach(button => button.disabled = true);
    reportMessage(`Reading ${files.length} FCS file(s)…`);
    try {
      const form = new FormData(); files.forEach(file => form.append('files', file));
      const response = await fetch('/api/upload', {method:'POST', body:form});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The FCS files could not be imported.');
      if (result.errors.length) {
        reportMessage(result.errors.map(error => `${error.filename}: ${AurekaIntake.readableError(error.error)}`).join('\n') + (result.samples.length ? '\nOther samples are ready. Open the analyzer to view them.' : ''), true);
      } else if (result.samples.length) {
        window.location.assign(`/?sample=${encodeURIComponent(result.samples[0].id)}&uploaded=${result.samples.length}`);
      }
    } catch (error) {reportMessage(error.message, true);}
    finally {reportUploading = false; document.querySelectorAll('[data-upload-trigger]').forEach(button => button.disabled = false);}
  }
});
