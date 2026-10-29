/* Responsive navigation shell: desktop sidebar, fixed five-item mobile dock, accessible More sheet. */
const ICON = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  review: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="m9 12 2 2 4-4"/>',
  transactions: '<path d="M5 3h14v18l-3.5-2-3.5 2-3.5-2L5 21V3Z"/><path d="M9 8h6M9 12h6"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18M7 14h3M14 14h3"/>',
  groups: '<path d="M20 8V6a2 2 0 0 0-2-2H5a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h15a2 2 0 0 0 2-2V9a1 1 0 0 0-1-1H6a2 2 0 0 1 0-4"/><path d="M16 14h6M17 14h.01"/>',
  people: '<path d="M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 20v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  plan: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  export: '<path d="M12 3v12m-4-4 4 4 4-4"/><path d="M5 17v3h14v-3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>',
  moon: '<path d="M20.5 13.1A9 9 0 0 1 10.9 3.5a9 9 0 1 0 9.6 9.6Z"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>'
};
function svg(name) {
  return '<svg class="nav-icon" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICON[name] || ICON.more) + '</svg>';
}
function brandLogo() {
  return '<svg class="brand-mark" width="32" height="32" viewBox="0 0 48 48" fill="none" aria-hidden="true">' +
    '<path fill="currentColor" d="M12 6h24l-6 8H17c-3 0-5 1.5-5 4 0 1.8 1 3 3.2 4.2l8.1 4.1-5.7 7.4-8-4.1C4 27 2 23.5 2 18.5 2 11.2 6.5 6 12 6Z"/>' +
    '<path fill="currentColor" d="m30.7 14.4 8 4.4C43.4 21.4 46 25.2 46 30c0 7.4-5.4 12-12.7 12H9l6-8h17.4c3 0 4.8-1.3 4.8-3.5 0-1.8-.8-3-3.4-4.4l-8.4-4.4 5.3-7.3Z"/></svg>';
}
const DESKTOP_TABS = [
  ['dashboard','Home'], ['review','Review'], ['transactions','History'],
  ['calendar','Calendar'], ['groups','Linked Money'], ['people','People & Loans'],
  ['plan','Plan'], ['settings','Settings']
];
const MOBILE_TABS = [
  ['dashboard','Home'], ['transactions','History'], ['groups','Linked Money'], ['calendar','Calendar']
];
const MORE_TABS = [
  ['review','Review'], ['people','People & Loans'], ['plan','Plan'], ['settings','Settings']
];
function renderShell() {
  const sidebar = DESKTOP_TABS.map(([route,label])=>
    '<a class="item" data-r="'+route+'" href="#/'+route+'">'+svg(route)+'<span>'+label+'</span>'+
    (route==='review'?'<span class="badge" data-review-badge hidden></span>':'')+'</a>'
  ).join('');
  const bottom = MOBILE_TABS.map(([route,label])=>
    '<a class="item" data-r="'+route+'" href="#/'+route+'">'+svg(route)+'<span class="tab-label">'+label+'</span></a>'
  ).join('');
  const more = MORE_TABS.map(([route,label])=>
    '<a class="more-item" href="#/'+route+'" data-more-link="'+route+'">'+svg(route)+'<span>'+label+'</span>'+
    (route==='review'?'<span class="badge" data-review-badge hidden></span>':'')+'</a>'
  ).join('');
  $('#app').innerHTML =
    '<header class="app-header" role="banner"><a class="header-brand" href="#/dashboard" aria-label="SpendFlow Home">'+brandLogo()+'<span>SpendFlow</span></a>'+
      '<button type="button" class="theme-toggle" id="theme-toggle" aria-label="Switch theme" title="Switch theme"></button></header>'+
    '<div class="app-frame"><nav class="nav" aria-label="Desktop navigation">'+sidebar+
       '<div class="grow"></div><button class="btn primary desk" id="nav-import">Import statement</button></nav>'+
       '<main id="main" tabindex="-1"></main></div>'+
    '<nav class="mobile-nav" aria-label="Mobile navigation">'+bottom+
       '<button type="button" class="item more-tab" id="mobile-more-button" aria-haspopup="dialog" aria-expanded="false" aria-controls="mobile-more">'+svg('more')+'<span class="tab-label">More</span></button></nav>'+
    '<div class="mobile-more-overlay" id="mobile-more" hidden>'+
      '<button type="button" class="mobile-more-backdrop" id="mobile-more-backdrop" aria-label="Close More menu"></button>'+
      '<section class="mobile-more-sheet" role="dialog" aria-modal="true" aria-labelledby="mobile-more-title">'+
        '<div class="more-heading"><h2 id="mobile-more-title">More</h2><button type="button" class="more-close" id="mobile-more-close" aria-label="Close More menu">'+svg('x')+'</button></div>'+
        '<nav class="more-links" aria-label="Additional pages">'+more+
          '<a class="more-item" id="mobile-export" href="/api/export.csv" download>'+svg('export')+'<span>Export transactions</span></a></nav>'+
      '</section></div>';
  $('#nav-import').onclick = openImport;
  $('#theme-toggle').onclick = toggleTheme;
  syncThemeButton();
  const moreButton = $('#mobile-more-button'), overlay = $('#mobile-more');
  moreButton.onclick = openMore;
  $('#mobile-more-close').onclick = () => closeMore();
  $('#mobile-more-backdrop').onclick = () => closeMore();
  $$('[data-more-link]',overlay).forEach(a => a.addEventListener('click',()=>closeMore(false)));
  $('#mobile-export').addEventListener('click',()=>closeMore(false));
  overlay.addEventListener('keydown', e => {
    if(e.key === 'Escape') { e.preventDefault(); closeMore(); return; }
    if(e.key !== 'Tab') return;
    const focusables = $$('a[href],button:not([disabled])', $('.mobile-more-sheet', overlay));
    const first = focusables[0], last = focusables[focusables.length-1];
    if(e.shiftKey && document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first.focus();}
  });
}
function openMore(){
  const overlay = $('#mobile-more'),button = $('#mobile-more-button');
  if(!overlay || !button || window.innerWidth>760) return;
  overlay.hidden=false;button.setAttribute('aria-expanded','true');
  document.body.classList.add('more-open');
  $('#mobile-more-close').focus();
}
function closeMore(restoreFocus=true){
  const overlay = $('#mobile-more'), button = $('#mobile-more-button');
  if(!overlay || overlay.hidden) return;
  overlay.hidden=true;
  document.body.classList.remove('more-open');
  if(button){button.setAttribute('aria-expanded','false');if(restoreFocus && window.innerWidth<=760)button.focus();}
}
window.addEventListener('resize',()=>{if(window.innerWidth>760)closeMore(false);});
