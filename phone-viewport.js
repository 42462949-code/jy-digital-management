/* Give non-scanning phone pages a desktop canvas fitted to the landscape screen.
   Only orientation/page changes reset the initial view; pinch zoom stays native. */
(()=>{
const normal='width=device-width, initial-scale=1, user-scalable=yes',canvasWidth=1440;
let scanning=false,lastMode='',lastContent='';
function phoneDevice(){if(navigator.userAgentData?.mobile||/iPhone|iPod|Android.*Mobile|Windows Phone/i.test(navigator.userAgent))return true;const side=Math.min(screen.width||innerWidth,screen.height||innerHeight);return !!window.matchMedia?.('(pointer: coarse)').matches&&side>0&&side<=700}
function landscapeDevice(){const type=screen.orientation?.type;if(type)return type.startsWith('landscape');if(typeof window.orientation==='number')return Math.abs(window.orientation)%180===90;return window.matchMedia?window.matchMedia('(orientation: landscape)').matches:innerWidth>innerHeight}
function syncPhoneViewport(scan){if(typeof scan==='boolean')scanning=scan;document.documentElement.classList.toggle('phone-device',phoneDevice());const height=window.innerHeight||document.documentElement.clientHeight;if(height>0&&document.documentElement.style.getPropertyValue('--jy-app-height')!==height+'px')document.documentElement.style.setProperty('--jy-app-height',height+'px');const fit=phoneDevice()&&!scanning&&landscapeDevice(),mode=fit?'landscape':'normal';document.documentElement.classList.toggle('phone-landscape-fit',fit);if(mode===lastMode)return;let meta=document.querySelector('meta[name="viewport"]');if(!meta){meta=document.createElement('meta');meta.name='viewport';document.head.append(meta)}let content=normal;if(fit){const screenWidth=Math.max(screen.width||0,screen.height||0)||Math.max(innerWidth,innerHeight),scale=Math.min(1,screenWidth/canvasWidth);content=`width=${canvasWidth}, initial-scale=${scale.toFixed(6)}, user-scalable=yes`}if(content!==lastContent){meta.setAttribute('content',content);lastContent=content}lastMode=mode}
window.syncPhoneViewport=syncPhoneViewport;
window.addEventListener('resize',()=>syncPhoneViewport());window.addEventListener('orientationchange',()=>syncPhoneViewport());screen.orientation?.addEventListener?.('change',()=>syncPhoneViewport());
syncPhoneViewport();
})();
