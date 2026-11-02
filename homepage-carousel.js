/* Three-second factory gallery, with an outgoing page turning over the next image. */
(()=>{'use strict';const original=window.showFactoryPhoto;let photo=null,index=0,timer=0,turn=null,page=null;
function stopTimer(){clearTimeout(timer);timer=0}
function finishTurn(){if(turn){turn.cancel();turn=null}page?.remove();page=null}
function schedule(){stopTimer();if(photo?.isConnected&&!document.hidden)timer=setTimeout(()=>show((index+1)%3),3000)}
function sync(){const current=document.getElementById('factoryPhoto');if(current===photo)return;stopTimer();finishTurn();photo=current;index=Number(document.querySelector('.factory-switch [aria-pressed="true"]')?.dataset.photo)||0;if(photo)schedule()}
function show(next){sync();if(!photo?.isConnected||!Number.isInteger(next)||next<0||next>2)return;if(next===index){schedule();return}finishTurn();const outgoing=photo.cloneNode(false);outgoing.removeAttribute('id');outgoing.alt='';outgoing.setAttribute('aria-hidden','true');original(next);index=next;
 if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches&&typeof photo.animate==='function'){page=document.createElement('div');page.className='factory-turn-page';page.setAttribute('aria-hidden','true');page.append(outgoing);photo.parentElement.append(page);const layer=page;turn=layer.animate([{transform:'rotateY(0deg)',filter:'brightness(1)',opacity:1,offset:0},{transform:'rotateY(-65deg)',filter:'brightness(.82)',opacity:1,offset:.7},{transform:'rotateY(-110deg)',filter:'brightness(.7)',opacity:0,offset:1}],{duration:720,easing:'cubic-bezier(.25,.6,.3,1)',fill:'forwards'});const active=turn;active.finished.then(()=>{layer.remove();if(turn===active){turn=null;page=null}}).catch(()=>layer.remove())}
 schedule()}
window.showFactoryPhoto=show;new MutationObserver(sync).observe(document.getElementById('app'),{childList:true});document.addEventListener('visibilitychange',()=>{if(document.hidden){stopTimer();finishTurn()}else{sync();schedule()}});sync();
})();
