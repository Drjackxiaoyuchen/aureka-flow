import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
const context={window:{},ResizeObserver:class{constructor(callback){this.callback=callback;}observe(){this.callback();}}};
vm.runInNewContext(fs.readFileSync('aureka_flow/static/gating.js','utf8'),context);
const G=context.window.AurekaGateDrawing;
const normalize=x=>JSON.parse(JSON.stringify(x));
const layout={xaxis:{_offset:100,_length:400,range:[10,110]},yaxis:{_offset:50,_length:200,range:[-50,50]}};
assert.deepEqual(normalize(G.coordinates(layout,[100,50])),[10,50]);
assert.deepEqual(normalize(G.coordinates(layout,[500,250])),[110,-50]);
assert.deepEqual(normalize(G.coordinates(layout,[300,150])),[60,0]);
assert.deepEqual(normalize(G.coordinates(layout,[-50,300])),[10,-50]);
assert.deepEqual(normalize(G.rectangle([80,20],[40,-10])),{kind:'rectangle',bounds:[40,80,-10,20]});
assert.deepEqual(normalize(G.ellipse([80,20],[40,-10])),{kind:'ellipse',bounds:[40,80,-10,20]});
assert.deepEqual(normalize(G.pixels(layout,[60,0])),[300,150]);
assert.equal(G.validPolygon([[0,0],[1,1]]),false);
assert.equal(G.validPolygon([[0,0],[1,1],[2,2]]),false);
assert.equal(G.validPolygon([[0,0],[1,0],[1,1],[0,1]]),true);
// Axis coordinates are already transformed by the backend; mapping must preserve them.
const transformed={xaxis:{_offset:20,_length:200,range:[.1,.9]},yaxis:{_offset:10,_length:100,range:[-.2,.8]}};
const point=G.coordinates(transformed,[120,60]);
assert.ok(Math.abs(point[0]-.5)<1e-12&&Math.abs(point[1]-.3)<1e-12);
// Exercise the original broken workflow: three separate clicks, then Finish.
function canvas(){return {style:{},handlers:{},capture:new Set(),innerHTML:'',
  getBoundingClientRect:()=>({left:0,top:0,width:600,height:300}),setAttribute(){},focus(){},
  addEventListener(name,handler){this.handlers[name]=handler;},
  setPointerCapture(id){this.capture.add(id);},hasPointerCapture(id){return this.capture.has(id);},releasePointerCapture(id){this.capture.delete(id);}};}
const svg=canvas(), plot={_fullLayout:layout,getBoundingClientRect:svg.getBoundingClientRect};
let result, error;
const drawing=G.create({plot,svg,onComplete:g=>result=normalize(g),onChange(){},onError:m=>error=m});
drawing.setTool('lasso');
function event(x,y){return {clientX:x,clientY:y,button:0,pointerId:1,preventDefault(){}};}
for(const [x,y] of [[100,250],[500,250],[300,50]]){svg.handlers.pointerdown(event(x,y));svg.handlers.pointerup(event(x,y));}
drawing.finish();
assert.equal(error,undefined);
assert.deepEqual(result,{kind:'polygon',vertices:[[10,-50],[110,-50],[60,50]]});
// An empty region can still produce geometric bounds; point hits are not required.
const svg2=canvas();let box;
G.create({plot,svg:svg2,onComplete:g=>box=normalize(g),onChange(){},onError:m=>{throw new Error(m);}});
svg2.handlers.pointerdown(event(300,150));svg2.handlers.pointermove(event(500,250));svg2.handlers.pointerup(event(500,250));
assert.deepEqual(box,{kind:'rectangle',bounds:[60,110,-50,0]});
// A histogram gesture can have zero vertical movement. Counts never become a dimension.
const svg3=canvas();let range;
const histogram=G.create({plot,svg:svg3,onComplete:g=>range=normalize(g),onChange(){},onError:m=>{throw new Error(m);}});
histogram.setTool('range');
svg3.handlers.pointerdown(event(300,150));svg3.handlers.pointermove(event(500,150));svg3.handlers.pointerup(event(500,150));
assert.deepEqual(range,{kind:'range',bounds:[60,110,null,null]});
histogram.setTool('range'); // Rendering the same plot controls must preserve a ready draft.
assert.equal(histogram.ready,true);
assert.match(svg3.innerHTML,/gate-draft/);
histogram.setTool('select');
assert.equal(histogram.ready,false);
const svg4=canvas();let oval;
const ellipses=G.create({plot,svg:svg4,onComplete:g=>oval=normalize(g),onChange(){},onError:m=>{throw new Error(m);}});
ellipses.setTool('ellipse');
svg4.handlers.pointerdown(event(450,200));svg4.handlers.pointermove(event(250,100));svg4.handlers.pointerup(event(250,100));
assert.deepEqual(oval,{kind:'ellipse',bounds:[47.5,97.5,-25,25]});
assert.match(svg4.innerHTML,/<ellipse class="gate-draft"/);
const svg5=canvas();let freehand;
const pencil=G.create({plot,svg:svg5,onComplete:g=>freehand=normalize(g),onChange(){},onError:m=>{throw new Error(m);}});
pencil.setTool('freehand');
svg5.handlers.pointerdown(event(200,100));
for(const p of [[400,100],[400,200],[200,200]])svg5.handlers.pointermove(event(...p));
svg5.handlers.pointerup(event(200,100));
assert.equal(freehand.kind,'polygon');assert.equal(pencil.ready,true);
assert.ok(G.validPolygon(freehand.vertices));
assert.deepEqual(freehand.vertices[0],[35,25]);
pencil.undo();assert.equal(pencil.ready,false);
pencil.finish();assert.equal(pencil.ready,true);
console.log('Gate checks passed: polygon, freehand, ellipse, rectangle, horizontal range, draft preservation and transformed coordinates.');
