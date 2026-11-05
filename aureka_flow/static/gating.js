/* Drawing geometry is independent of displayed point selection or WebGL hit tests. */
window.AurekaGateDrawing = (() => {
  function coordinates(layout, point) {
    const x = layout.xaxis, y = layout.yaxis;
    const px = Math.max(x._offset, Math.min(x._offset + x._length, point[0]));
    const py = Math.max(y._offset, Math.min(y._offset + y._length, point[1]));
    return [x.range[0] + (px-x._offset)/x._length*(x.range[1]-x.range[0]),
      y.range[1] - (py-y._offset)/y._length*(y.range[1]-y.range[0])];
  }
  function pixels(layout, point) {
    const x=layout.xaxis,y=layout.yaxis;
    return [x._offset+(point[0]-x.range[0])/(x.range[1]-x.range[0])*x._length,
      y._offset+(y.range[1]-point[1])/(y.range[1]-y.range[0])*y._length];
  }
  const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  function rectangle(a,b) {return {kind:'rectangle',bounds:[Math.min(a[0],b[0]),Math.max(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[1],b[1])]};}
  function validPolygon(points) {
    if(points.length<3)return false;
    const [a,b]=points, scale=Math.max(...points.map(p=>Math.max(Math.abs(p[0]-a[0]),Math.abs(p[1]-a[1]))),1e-12);
    return points.slice(2).some(c=>Math.abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))>1e-12*scale*scale);
  }
  function create({plot,svg,onComplete,onChange,onError,canDraw=()=>true}) {
    let tool='select', points=[], ready=false, pointer=null, drag=null, rectangleEnd=null, completedAt=0;
    const layout=()=>plot._fullLayout;
    const point=event=>{const r=svg.getBoundingClientRect();return [event.clientX-r.left,event.clientY-r.top];};
    function clear() {points=[];ready=false;pointer=null;drag=null;rectangleEnd=null;onChange(null);sync();}
    function sync() {
      const l=layout();if(!l?.xaxis?.range || !l?.yaxis?.range)return;
      const r=plot.getBoundingClientRect();svg.setAttribute('viewBox',`0 0 ${r.width} ${r.height}`);
      svg.style.display=tool==='pan'?'none':'block';
      const x=l.xaxis,y=l.yaxis;
      let markup=`<rect class="gate-hit-area" x="${x._offset}" y="${y._offset}" width="${x._length}" height="${y._length}" fill="transparent" pointer-events="all"/>`;
      let display=points.map(p=>pixels(l,p));
      if((tool==='select'||tool==='range') && points.length && rectangleEnd) {
        const a=display[0],b=pixels(l,rectangleEnd);
        markup+=`<rect class="gate-draft" x="${Math.min(a[0],b[0])}" y="${tool==='range'?y._offset:Math.min(a[1],b[1])}" width="${Math.abs(a[0]-b[0])}" height="${tool==='range'?y._length:Math.abs(a[1]-b[1])}"/>`;
      } else if(tool==='lasso' && display.length) {
        markup+=`<path class="gate-draft" d="${display.map((p,i)=>`${i?'L':'M'} ${p[0]} ${p[1]}`).join(' ')}${ready?' Z':''}"/>`;
        markup+=display.map((p,i)=>`<circle class="gate-vertex ${i===0?'first':''}" cx="${p[0]}" cy="${p[1]}" r="${i===0?5:3.5}"/>`).join('');
      }
      svg.innerHTML=markup;
    }
    function complete(geometry) {
      ready=true;completedAt=Date.now();pointer=null;drag=null;onComplete(geometry);
      onChange({ready:true,kind:geometry.kind,vertices:points.length});sync();
    }
    function finish() {
      if(!validPolygon(points)){onError('Place at least three distinct, non-collinear polygon corners.');return;}
      complete({kind:'polygon',vertices:points.map(p=>[...p])});
    }
    svg.addEventListener('pointerdown',event=>{
      if(tool==='pan'||event.button!==0||!canDraw())return;
      const l=layout(),p=point(event),x=l?.xaxis,y=l?.yaxis;
      if(!x||p[0]<x._offset||p[0]>x._offset+x._length||p[1]<y._offset||p[1]>y._offset+y._length)return;
      if(ready&&Date.now()-completedAt<250)return;
      event.preventDefault();svg.focus({preventScroll:true});
      if(ready)clear();
      pointer={id:event.pointerId,start:p,data:coordinates(l,p),moved:false};
      svg.setPointerCapture(event.pointerId);
      if(tool==='select'||tool==='range'){points=[pointer.data];rectangleEnd=pointer.data;}
      else drag=[pointer.data];
      sync();
    });
    svg.addEventListener('pointermove',event=>{
      if(!pointer||event.pointerId!==pointer.id)return;
      event.preventDefault();const p=point(event),data=coordinates(layout(),p);
      if(distance(p,pointer.start)>5)pointer.moved=true;
      if(tool==='select'||tool==='range')rectangleEnd=data;
      else if(pointer.moved&&drag.length<500&&distance(p,pixels(layout(),drag[drag.length-1]))>=4){
        drag.push(data);points=[...drag];onChange({ready:false,kind:'polygon',vertices:points.length});
      }
      sync();
    });
    svg.addEventListener('pointerup',event=>{
      if(!pointer||event.pointerId!==pointer.id)return;
      event.preventDefault();const p=point(event),data=coordinates(layout(),p),was=pointer;pointer=null;
      if(svg.hasPointerCapture(event.pointerId))svg.releasePointerCapture(event.pointerId);
      if(tool==='select'||tool==='range'){
        if(Math.abs(p[0]-was.start[0])<4||(tool==='select'&&Math.abs(p[1]-was.start[1])<4)){clear();onError(tool==='range'?'Drag horizontally across the values you want to include.':'Drag a rectangle with some width and height.');return;}
        rectangleEnd=data;
        complete(tool==='range'?{kind:'range',bounds:[Math.min(was.data[0],data[0]),Math.max(was.data[0],data[0]),null,null]}:rectangle(was.data,data));
      }else if(was.moved){points=[...drag,data];finish();}
      else {
        if(points.length>=3&&distance(p,pixels(layout(),points[0]))<9){finish();return;}
        if(!points.length||distance(p,pixels(layout(),points[points.length-1]))>=3)points.push(data);
        if(points.length>1000){points.pop();onError('A polygon can have at most 1,000 vertices.');}
        onChange({ready:false,kind:'polygon',vertices:points.length});sync();
      }
    });
    svg.addEventListener('pointercancel',()=>clear());
    svg.addEventListener('dblclick',event=>{event.preventDefault();if(tool==='lasso'&&!ready)finish();});
    svg.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();clear();}
      else if(event.key==='Enter'&&tool==='lasso'){event.preventDefault();finish();}
      else if((event.key==='Backspace'||event.key==='Delete')&&tool==='lasso'){event.preventDefault();undo();}
    });
    function undo(){if(tool==='lasso'){points.pop();ready=false;onChange(points.length?{ready:false,kind:'polygon',vertices:points.length}:null);sync();}}
    const observer=new ResizeObserver(sync);observer.observe(plot);
    return {clear,sync,finish,undo,setTool(value){if(tool!==value){tool=value;clear();}else sync();},get ready(){return ready;}};
  }
  return {create,coordinates,pixels,rectangle,validPolygon};
})();
