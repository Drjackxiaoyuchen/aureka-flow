/* Shared, local-only FCS intake for the analyzer and validation report. */
window.AurekaIntake = {
  readableError(message) {
    return /offset.*off by 1|offset discrepancy/i.test(String(message))
      ? 'This file has inconsistent FCS data offsets. Re-export it as an FCS file, then upload the new copy.'
      : String(message);
  },
  bind({onFiles, onError, isBusy = () => false}) {
    const input = document.querySelector('[data-fcs-input]');
    const overlay = document.querySelector('.file-drop-overlay');
    let depth = 0;
    const hasFiles = event => Array.from(event.dataTransfer?.types || []).includes('Files');
    const hide = () => {depth = 0; if (overlay) overlay.hidden = true; document.querySelectorAll('[data-fcs-drop]').forEach(el => el.classList.remove('drag'));};
    const handle = async list => {
      if (isBusy()) {onError('Please wait for the current operation to finish, then upload your files.'); return;}
      const files = Array.from(list || []);
      if (!files.length) return;
      const invalid = files.filter(file => !/\.fcs$/i.test(file.name));
      if (invalid.length) {onError('Choose FCS files (.fcs). Unsupported file(s): ' + invalid.map(file => file.name).join(', ')); return;}
      if (files.length > 24) {onError('Choose at most 24 FCS files at a time.'); return;}
      const fileLimit = window.AurekaIntake.limits?.file_bytes || 100 * 1024 * 1024;
      const large = files.find(file => file.size > fileLimit);
      if (large) {onError(`${large.name} exceeds the ${Math.round(fileLimit/1024**2)} MB limit per file.`); return;}
      await onFiles(files);
    };
    document.querySelectorAll('[data-upload-trigger]').forEach(el => el.addEventListener('click', () => input.click()));
    input.addEventListener('change', async () => {try {await handle(input.files);} finally {input.value = '';}});
    document.addEventListener('dragenter', event => {
      if (!hasFiles(event)) return;
      event.preventDefault(); depth++; if (overlay) overlay.hidden = false;
    });
    document.addEventListener('dragover', event => {
      if (!hasFiles(event)) return;
      event.preventDefault(); event.dataTransfer.dropEffect = 'copy';
    });
    document.addEventListener('dragleave', event => {
      if (!hasFiles(event) && !depth) return;
      depth = Math.max(0, depth - 1); if (!depth) hide();
    });
    document.addEventListener('drop', async event => {
      if (!hasFiles(event) && !event.dataTransfer?.files?.length) return;
      event.preventDefault(); hide(); await handle(event.dataTransfer.files);
    });
    window.addEventListener('blur', hide);
  }
};
