import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const context={window:{}};vm.runInNewContext(fs.readFileSync('aureka_flow/static/axis-ranges.js','utf8'),context);
const R=context.window.AurekaAxisRanges,plain=x=>JSON.parse(JSON.stringify(x));
assert.equal(R.parse('',''),null);
assert.deepEqual(plain(R.parse(' -1e2 ','2e3')) ,[-100,2000]);
for(const pair of [['','1'],['0',''],['NaN','1'],['0','Infinity'],['2','1'],['1','1'],['-1e308','1e308']])assert.throws(()=>R.parse(...pair));
const axis={channel:'FITC$-A',transform:{kind:'linear',t:262144,m:4.5,w:.5,a:0}};
const linear=R.channelKey(axis,'raw');
assert.equal(linear,R.channelKey({...axis,transform:{...axis.transform,t:100}},'raw'));
assert.notEqual(linear,R.channelKey(axis,'fcs'));
assert.notEqual(linear,R.channelKey({...axis,channel:'FITC-A'},'raw'));
const logicle=R.channelKey({...axis,transform:{...axis.transform,kind:'logicle'}},'raw');
assert.notEqual(linear,logicle);
assert.notEqual(logicle,R.channelKey({...axis,transform:{...axis.transform,kind:'logicle',w:.2}},'raw'));
const ranges=R.create(),keys={x:'x-coordinates',y:'y-coordinates'};
ranges.set(keys.x,[.1,.8]);ranges.set(keys.y,[-.2,1]);
const returned=ranges.get(keys.x);returned[0]=99;assert.equal(ranges.get(keys.x)[0],.1);
const layout={xaxis:{title:'X'},yaxis:{rangemode:'tozero'}};
ranges.apply(layout,keys);
assert.deepEqual(plain(layout),{xaxis:{title:'X',range:[.1,.8],autorange:false},yaxis:{rangemode:'tozero',range:[-.2,1],autorange:false}});
// Zoom and pan retain the same transformed coordinates across a redraw/sample switch.
ranges.capture(keys,{'xaxis.range[0]':.3,'xaxis.range[1]':.6,'yaxis.range':[-1,2]});
const redraw={xaxis:{},yaxis:{}};ranges.apply(redraw,keys);
assert.deepEqual(plain(redraw.xaxis.range),[.3,.6]);assert.deepEqual(plain(redraw.yaxis.range),[-1,2]);
// An unrelated relayout/resize or incomplete event cannot overwrite a display window.
ranges.capture(keys,{width:900,'xaxis.range[0]':4});assert.equal(ranges.get(keys.x)[0],.3);
ranges.capture(keys,{'xaxis.autorange':true});assert.equal(ranges.get(keys.x),null);assert.equal(ranges.get(keys.y)[0],-1);
const other={xaxis:{range:[0,10]},yaxis:{}};ranges.apply(other,{x:linear,y:'counts'});
assert.deepEqual(plain(other),{xaxis:{range:[0,10]},yaxis:{}});
// Bound the in-memory coordinate history. No browser storage/sample data is serialized.
const bounded=R.create(2);for(let i=0;i<3;i++)bounded.set('axis-'+i,[i,i+1]);
assert.equal(bounded.get('axis-0'),null);assert.deepEqual(plain(bounded.get('axis-2')),[2,3]);
console.log('Axis range checks passed: validation, exact coordinate keys, independent axes, zoom/pan capture, autorange and bounded history.');
