(function(){
  function go(url){
    if(!url) return;
    window.location.href = url;
  }

  document.addEventListener('click', function(e){
    const noNav = e.target.closest('a,button,input,textarea,select');
    if(noNav) return;
    const panel = e.target.closest('[data-href]');
    if(panel) go(panel.getAttribute('data-href'));
  });

  document.addEventListener('keydown', function(e){
    if(e.key !== 'Enter' && e.key !== ' ') return;
    const panel = document.activeElement && document.activeElement.closest && document.activeElement.closest('[data-href]');
    if(panel){
      e.preventDefault();
      go(panel.getAttribute('data-href'));
    }
  });

  document.addEventListener('DOMContentLoaded', function(){
    document.querySelectorAll('[data-href]').forEach(el=>{
      el.setAttribute('tabindex','0');
      el.setAttribute('role','link');
      if(!el.getAttribute('data-tip')){
        el.setAttribute('data-tip','Open related Cerberus Operations Console page.');
      }
    });
  });
})();
