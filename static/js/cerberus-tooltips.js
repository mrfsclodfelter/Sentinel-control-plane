(function(){
  let tip;
  function ensureTip(){
    if(!tip){
      tip=document.createElement('div');
      tip.id='cerberus-global-tooltip';
      document.body.appendChild(tip);
    }
    return tip;
  }
  function textFor(el){
    return el.getAttribute('data-tip') || el.getAttribute('title') || '';
  }
  function show(el){
    const text=textFor(el);
    if(!text) return;
    if(el.getAttribute('title')){
      el.setAttribute('data-native-title', el.getAttribute('title'));
      el.removeAttribute('title');
    }
    const t=ensureTip();
    t.textContent=text;
    t.classList.add('visible');
    position(el);
  }
  function hide(){
    if(tip) tip.classList.remove('visible');
  }
  function position(el){
    if(!tip || !tip.classList.contains('visible')) return;
    const r=el.getBoundingClientRect();
    const margin=14;
    const w=tip.offsetWidth || 320;
    const h=tip.offsetHeight || 80;
    let left=r.left + (r.width/2) - (w/2);
    let top=r.top - h - 12;

    if(top < margin) top = r.bottom + 12;
    if(left < margin) left = margin;
    if(left + w > window.innerWidth - margin) left = window.innerWidth - w - margin;
    if(top + h > window.innerHeight - margin) top = Math.max(margin, window.innerHeight - h - margin);

    tip.style.left=left + 'px';
    tip.style.top=top + 'px';
  }
  document.addEventListener('mouseover', e=>{
    const el=e.target.closest('[data-tip], [title]');
    if(el && !el.closest('#cerberus-global-tooltip')) show(el);
  });
  document.addEventListener('mousemove', e=>{
    const el=e.target.closest('[data-tip]');
    if(el) position(el);
  });
  document.addEventListener('mouseout', e=>{
    const from=e.target.closest('[data-tip]');
    const to=e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('[data-tip]');
    if(from && from!==to) hide();
  });
  document.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
})();
