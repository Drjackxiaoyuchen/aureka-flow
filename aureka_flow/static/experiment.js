/* Experiment metadata is a user declaration. Never infer replicate identities. */
let experimentManifest = null;
$('experiment-template').onclick = () => run(() => download('/api/experiment-template', comparisonSpec(), 'aureka-sample-manifest.json'));
$('load-manifest').onclick = () => $('manifest-file').click();
$('manifest-file').onchange = () => run(async () => {
  const file = $('manifest-file').files[0];
  if (!file) return;
  try {
    if (file.size > 1024 * 1024) throw new Error('Choose a sample manifest smaller than 1 MiB.');
    const manifest = JSON.parse(await file.text());
    if (manifest?.schema_version !== 'yeast-facs-samples/v1' || !Array.isArray(manifest.samples)) throw new Error('Choose an edited Aureka Flow sample manifest.');
    experimentManifest = manifest;
    $('manifest-status').textContent = `${file.name} loaded · ${manifest.samples.length} declared sample records. Identities will be checked against the selected sources when generating the report.`;
  } finally { $('manifest-file').value = ''; }
});
$('clear-manifest').onclick = () => {
  experimentManifest = null;
  $('manifest-status').textContent = 'No manifest loaded. The report will mark condition as Unspecified and replicate/batch identities as unknown.';
};
$('export-experiment').onclick = () => run(async () => {
  await download('/api/export/experiment', {analysis: comparisonSpec(), manifest: experimentManifest}, 'aureka-experiment-report.zip');
  notice('Experiment report downloaded. Extract the ZIP and open index.html. Review QC, denominators and replicate/batch warnings before interpreting comparisons.');
}, 'Preparing experiment report…');
$('acquisition-qc').onclick = () => run(async () => {
  $('qc-content').textContent = JSON.stringify(await json(`/api/qc/${state.selected}`), null, 2);
  $('qc-dialog').showModal();
});
$('close-qc').onclick = () => $('qc-dialog').close();
