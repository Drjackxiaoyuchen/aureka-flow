/* Display windows only. Never included in analysis/gate API requests. */
window.AurekaAxisRanges = (() => {
  function parse(min, max, label='Axis') {
    const a=String(min).trim(),b=String(max).trim();
    if(!a&&!b)return null;
    if(!a||!b)throw new Error(`${label}: enter both Min and Max, or leave both blank for Auto.`);
    const range=[Number(a),Number(b)];
    if(!range.every(Number.isFinite)||range[0]>=range[1]||!Number.isFinite(range[1]-range[0]))
      throw new Error(`${label}: use finite numbers with Min < Max.`);
    return range;
  }
  function channelKey(axis, compensation) {
    const t=axis.transform;
    // Linear ignores transform parameters; their inactive values cannot change units.
    return JSON.stringify(['channel',axis.channel,compensation,t.kind,
      ...(t.kind==='linear'?[]:t.kind==='asinh'?[t.t,t.m,t.a]:[t.t,t.m,t.w,t.a])]);
  }
  function create(limit=64) {
    const ranges=new Map();
    function get(key){return ranges.has(key)?[...ranges.get(key)]:null;}
    function set(key,range){
      ranges.delete(key);
      if(range){ranges.set(key,[...range]);while(ranges.size>limit)ranges.delete(ranges.keys().next().value);}
    }
    function apply(layout, keys){
      for(const axis of ['x','y']){const range=get(keys[axis]);if(range)Object.assign(layout[axis+'axis'],{range,autorange:false});}
      return layout;
    }
    function capture(keys,event){
      for(const axis of ['x','y']){
        const prefix=axis+'axis';
        if(event[prefix+'.autorange']===true){set(keys[axis],null);continue;}
        const range=event[prefix+'.range']??[event[prefix+'.range[0]'],event[prefix+'.range[1]']];
        if(Array.isArray(range)&&range.length===2&&range.every(Number.isFinite)&&range[0]<range[1])set(keys[axis],range);
      }
    }
    return {get,set,apply,capture};
  }
  return {parse,channelKey,create};
})();
