// Test file-input and whole-page drop behavior without browser automation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element extends EventTarget {
  hidden = true;
  value = 'selected';
  clicks = 0;
  classList = {remove() {}};
  click() {this.clicks++;}
}
const input = new Element(), overlay = new Element(), trigger = new Element();
const document = new EventTarget(), window = new EventTarget();
document.querySelector = selector => selector === '[data-fcs-input]' ? input : overlay;
document.querySelectorAll = selector => selector === '[data-upload-trigger]' ? [trigger] : [];
vm.runInNewContext(fs.readFileSync(new URL('../aureka_flow/static/intake.js', import.meta.url), 'utf8'), {window, document, Array, String});
const errors = [], batches = [];
let busy = false;
window.AurekaIntake.bind({onFiles: async files => batches.push(files), onError: message => errors.push(message), isBusy: () => busy});
const tick = () => new Promise(resolve => setImmediate(resolve));
function event(type, files = [], types = ['Files']) {
  const value = new Event(type, {cancelable:true});
  value.dataTransfer = {types, files};
  document.dispatchEvent(value); return value;
}
const file = {name:'my-sample.FCS', size:1024};
trigger.dispatchEvent(new Event('click'));
assert.equal(input.clicks, 1);
input.files = [file];input.dispatchEvent(new Event('change'));await tick();
assert.equal(batches.length, 1);assert.equal(input.value, '');
assert.equal(event('dragenter').defaultPrevented, true);assert.equal(overlay.hidden, false);
event('dragenter');event('dragleave');assert.equal(overlay.hidden, false);
assert.equal(event('dragover').dataTransfer.dropEffect, 'copy');
const drop = event('drop', [file]);await tick();
assert.equal(drop.defaultPrevented, true);assert.equal(overlay.hidden, true);assert.equal(batches.length, 2);
event('drop', [{name:'plot.png',size:100}]);await tick();assert.match(errors.at(-1), /Unsupported/);
event('drop', [{name:'large.fcs',size:101*1024*1024}]);await tick();assert.match(errors.at(-1), /100 MB/);
event('drop', Array.from({length:25}, () => file));await tick();assert.match(errors.at(-1), /24/);
busy = true;event('drop', [file]);await tick();assert.match(errors.at(-1), /wait/);assert.equal(batches.length, 2);
busy = false;event('dragenter');window.dispatchEvent(new Event('blur'));assert.equal(overlay.hidden, true);
assert.equal(event('drop', [], ['text/plain']).defaultPrevented, false);
assert.match(window.AurekaIntake.readableError('data offset that is off by 1. Set ignore_offset_error=True'), /Re-export/);
assert.equal(window.AurekaIntake.readableError('No events'), 'No events');
console.log('FCS intake checks passed: file picker, global drop, nested drag, validation, busy state and error wording.');
