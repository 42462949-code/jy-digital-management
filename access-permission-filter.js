/* Excel-style filters for the isolated, editable user permission draft. */
(()=>{'use strict';
const E=JYBusiness.E,names=['项次','表名','控制节点','权限'];let model=null,popup=null;
const busy=()=>!!window.JYAccess?.isLocked();
const values=row=>[String(row.index+1),row.table,row.node,row.grant.value];
const matches=(row,except=null)=>[...model.filters].every(([column,allowed])=>column===except||allowed.has(values(row)[column]));
const compare=(a,b)=>a===''?(b===''?0:1):b===''?-1:compareCells(a,b);
function close(focus=false){const anchor=popup?.anchor;popup?.panel.remove();if(anchor)anchor.setAttribute('aria-expanded','false');popup=null;if(focus&&anchor?.isConnected)anchor.focus()}
function refresh(){
 if(!model?.table.isConnected){close();return}
 const table=model.table;for(const row of model.rows)row.element.hidden=!matches(row);
 table.querySelector('.access-filter-empty')?.remove();
 const ordered=model.rows.slice();if(model.sort){const {column,direction}=model.sort;ordered.sort((a,b)=>{const av=values(a)[column],bv=values(b)[column];return av===''||bv===''?compare(av,bv)||a.index-b.index:(direction==='asc'?1:-1)*compare(av,bv)||a.index-b.index})}
 const current=[...table.tBodies[0].rows];if(ordered.some((row,i)=>row.element!==current[i])){const active=document.activeElement,fragment=document.createDocumentFragment();ordered.forEach(row=>fragment.append(row.element));table.tBodies[0].append(fragment);if(active?.isConnected&&table.contains(active))active.focus({preventScroll:true})}
 const count=model.rows.filter(row=>!row.element.hidden).length;
 if(!count){const tr=document.createElement('tr');tr.className='access-filter-empty';tr.innerHTML='<td colspan="'+table.tHead.rows[0].cells.length+'">暂无匹配项目</td>';table.tBodies[0].append(tr)}
 for(const button of table.querySelectorAll('.access-permission-funnel')){const column=Number(button.dataset.column),active=model.filters.has(column);button.classList.toggle('active',active);button.closest('th').classList.toggle('column-filtered',active);button.title=names[column]+' 筛选'+(active?'（已筛选）':'')}
 document.getElementById('accessFilterSummary')?.remove();
 if(model.filters.size){const summary=document.createElement('span');summary.id='accessFilterSummary';summary.append(' 当前显示 '+count+' 项 ');const clear=document.createElement('button');clear.type='button';clear.textContent='清除筛选';clear.onclick=()=>clearFilters();summary.append(clear);document.getElementById('accessTemplateCount').append(summary)}
 window.JYAccess?.syncBatchSelection();
}
function clearFilters(column=null){if(!model||busy())return;if(column===null)model.filters.clear();else model.filters.delete(column);close();refresh()}
function options(){if(!popup)return [];const q=popup.query.trim().toLocaleLowerCase();return q?popup.values.filter(value=>(value||'（空白）').toLocaleLowerCase().includes(q)):popup.values}
function renderOptions(){
 if(!popup)return;const list=popup.panel.querySelector('.excel-filter-list'),items=options(),scroll=list.scrollTop,start=Math.max(0,Math.min(Math.max(0,items.length-50),Math.floor(scroll/26)-5)),end=Math.min(items.length,start+50);
 list.replaceChildren();if(!items.length){list.innerHTML='<div class="excel-no-values">无匹配项</div>'}else{const top=document.createElement('div');top.style.height=start*26+'px';list.append(top);for(const value of items.slice(start,end)){const label=document.createElement('label');label.className='excel-value';label.title=value||'（空白）';const check=document.createElement('input');check.type='checkbox';check.checked=popup.selected.has(value);check.onchange=()=>{if(check.checked)popup.selected.add(value);else popup.selected.delete(value);updateAll()};const text=document.createElement('span');text.textContent=value||'（空白）';label.append(check,text);list.append(label)}const bottom=document.createElement('div');bottom.style.height=(items.length-end)*26+'px';list.append(bottom)}list.scrollTop=scroll;updateAll();
}
function updateAll(){if(!popup)return;const items=options(),count=items.filter(v=>popup.selected.has(v)).length,all=popup.panel.querySelector('.access-filter-all');all.checked=items.length>0&&items.length===count;all.indeterminate=count>0&&count<items.length;all.disabled=!items.length;popup.panel.querySelector('.access-filter-all-label').textContent=popup.query?'（全选搜索结果）':'（全选）';popup.panel.querySelector('.access-filter-value-count').textContent=items.length}
function position(){if(!popup)return;if(!popup.anchor.isConnected){close();return}const {panel,anchor}=popup,rect=anchor.getBoundingClientRect(),box=panel.getBoundingClientRect(),vw=innerWidth,vh=innerHeight;panel.style.left=Math.max(8,Math.min(vw-box.width-8,rect.right-box.width))+'px';panel.style.top=Math.max(8,rect.bottom+box.height+5<=vh-8?rect.bottom+5:rect.top-box.height-5)+'px'}
function open(column,anchor){
 if(!model?.table.isConnected||busy())return;if(popup?.column===column){close(true);return}close();
 const allValues=[...new Set(model.rows.map(row=>values(row)[column]))],items=[...new Set(model.rows.filter(row=>matches(row,column)).map(row=>values(row)[column]))].sort(compare),selected=new Set(model.filters.has(column)?items.filter(v=>model.filters.get(column).has(v)):items),panel=document.createElement('div');panel.id='accessPermissionFilter';panel.className='excel-filter access-permission-filter';panel.setAttribute('role','dialog');panel.setAttribute('aria-label','筛选 · '+names[column]);
 panel.innerHTML='<div class="excel-filter-name">'+E(names[column])+'</div><button type="button" class="excel-command" data-sort="asc"><span aria-hidden="true">↑</span>'+(column===0?'从小到大排序':'升序排序（A → Z）')+'</button><button type="button" class="excel-command" data-sort="desc"><span aria-hidden="true">↓</span>'+(column===0?'从大到小排序':'降序排序（Z → A）')+'</button><div class="excel-divider"></div><button type="button" class="excel-command access-filter-clear" '+(model.filters.has(column)?'':'disabled')+'><span aria-hidden="true">⌫</span>清除此列筛选</button><div class="excel-search"><input type="search" placeholder="搜索" aria-label="搜索筛选值" autocomplete="off"><span aria-hidden="true">⌕</span></div><label class="excel-select-all"><input type="checkbox" class="access-filter-all"><span class="access-filter-all-label">（全选）</span><small class="access-filter-value-count"></small></label><div class="excel-filter-list" role="group" aria-label="筛选值列表"></div><div class="excel-filter-footer"><button type="button" class="access-filter-cancel">取消</button><button type="button" class="excel-confirm">确定</button></div>';
 popup={column,anchor,panel,values:items,allValues,query:'',selected};anchor.setAttribute('aria-expanded','true');document.getElementById('modal').append(panel);
 panel.querySelector('.excel-search input').oninput=event=>{popup.query=event.target.value;panel.querySelector('.excel-filter-list').scrollTop=0;renderOptions()};panel.querySelector('.excel-filter-list').onscroll=renderOptions;
 panel.querySelector('.access-filter-all').onchange=event=>{for(const value of options())if(event.target.checked)popup.selected.add(value);else popup.selected.delete(value);renderOptions()};
 panel.querySelector('.access-filter-clear').onclick=()=>clearFilters(column);panel.querySelector('.access-filter-cancel').onclick=()=>close(true);
 panel.querySelector('.excel-confirm').onclick=()=>{if(busy())return;const picked=new Set(popup.query?options().filter(v=>popup.selected.has(v)):popup.selected);if(allValues.length===picked.size&&allValues.every(v=>picked.has(v)))model.filters.delete(column);else model.filters.set(column,picked);close();refresh()};
 for(const button of panel.querySelectorAll('[data-sort]'))button.onclick=()=>{if(busy())return;model.sort={column,direction:button.dataset.sort};close();refresh()};
 renderOptions();position();panel.querySelector('.excel-search input').focus();
}
function init(table){
 close();const offset=table.querySelector('.access-batch-check-head')?1:0;
 model={table,filters:new Map(),sort:null,rows:[...table.tBodies[0].rows].map(element=>{const grant=element.querySelector('.access-grant');return {element,index:Number(grant.dataset.index),table:element.cells[offset+1].textContent,node:element.cells[offset+2].textContent,grant}})};
 table.querySelectorAll('.access-permission-funnel').forEach(button=>button.remove());
 [...table.tHead.rows[0].cells].slice(offset).forEach((header,column)=>{const button=document.createElement('button');button.type='button';button.className='funnel access-permission-funnel';button.dataset.column=column;button.setAttribute('aria-label',names[column]+' 筛选');button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');button.title=names[column]+' 筛选';button.textContent='▾';button.onpointerdown=event=>event.stopPropagation();button.onclick=event=>{event.preventDefault();event.stopPropagation();open(column,button)};header.append(button)});
 table.onchange=event=>{if(event.target.matches('.access-grant'))refresh()};document.getElementById('accessForm').noValidate=true;refresh();
}
document.addEventListener('pointerdown',event=>{if(popup&&!popup.panel.contains(event.target)&&!event.target.closest('.access-permission-funnel'))close()},true);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&popup){event.preventDefault();event.stopImmediatePropagation();close(true)}},true);
document.getElementById('modal').addEventListener('close',()=>{if(!document.getElementById('modal').open){close();model=null}});
document.getElementById('modal').addEventListener('scroll',event=>{if(event.target===document.getElementById('modal')||event.target.matches?.('.access-permission-scroll'))close()},true);window.addEventListener('resize',position);
window.JYAccessPermissionFilter={init,refresh,close,reveal(grant){clearFilters();grant?.focus()}};
})();
