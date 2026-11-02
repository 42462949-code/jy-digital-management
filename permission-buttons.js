/* Hide unavailable business actions; explicitly retained controls stay gray and inert. */
(()=>{'use strict';
const locks=new WeakMap();
const can=(table,action)=>window.JYAccess?JYAccess.can(table,action):window.JYEnterprise?.enabled?JYEnterprise.can(table,action):true;
// Local generation uses one permission for the complete draft workflow.
const draftCan=action=>JYEnterprise.enabled?can(1,action):can(0,'generate_work');
function actionRule(table,name){
 if(table===4&&name==='确定')return ()=>can(4,'update')||can(4,'create');
 const action=JYEnterprise.actionPermission?.(table,name)||({新增:'create',新增班组:'create',删除:'delete',删除班组:'delete'}[name]||JYAccess.nodes[name]||(/导入|上传/.test(name)?'import':/导出/.test(name)?'export':name.includes('下推')?(table===1?'generate_report':'generate_work'):'update'));
 return ()=>can(table,action)&&(!(table===10&&['新增','修改'].includes(name))||can(10,'financial_view'));
}
function rule(button){
 const click=(button.getAttribute('onclick')||'').trim(),table=typeof current==='number'?current:-1;
 if(button.dataset.permissionAction)return ()=>can(Number(button.dataset.permissionTable),button.dataset.permissionAction)&&(!button.dataset.permissionFinancial||can(Number(button.dataset.permissionTable),'financial_view'));
 if(button.type==='submit'&&/confirmScanQuantity\(/.test(button.form?.getAttribute('onsubmit')||''))return ()=>can(8,'create');
 const action=click.match(/^action\(['"]([^'"]+)['"]\)/);if(action)return actionRule(table,action[1]);
 if(button.matches('.table-save-action'))return ()=>can(table,'create')||can(table,'update');
 if(button.matches('.table-delete-action')||/^confirmTableRowsDeletion\(/.test(click)||button.id==='salesDeleteConfirm')return ()=>can(table,'delete');
 if(/^(startScanner|submitManualScan|chooseScanImage|confirmScanQuantity)\(/.test(click))return ()=>can(8,'create');
 if(/^(clearScanRecords|confirmClearScanRecords)\(/.test(click))return ()=>can(8,'delete');
 if(button.id==='scanSubmit'||/^confirmSubmitScans\(/.test(click))return ()=>can(8,'scan_submit');
 if(button.matches('.enterprise-correct-scan'))return ()=>can(8,'scan_correct');
 if(/^JYInventory\.drillDown\(/.test(click))return ()=>can(13,'view');
 if(button.id==='inventoryVoucherConfirm')return ()=>can(12,'generate_inventory');
 if(/^JYHourlyOutput\.exportExcel\(/.test(click))return ()=>can(11,'export');
 if(/^JYWorkOrders\.(save|moveRows|requestRemoveRows|discard)\(/.test(click))return ()=>draftCan('draft_edit');
 if(/^JYWorkOrders\.print\(/.test(click))return ()=>draftCan('report_print');
 if(/^JYWorkOrders\.confirm\(/.test(click))return ()=>draftCan('confirm_work');
 if(/^JYWorkOrders\.createDraft\(/.test(click))return ()=>can(0,'generate_work');
 if(/^JYProductionReportDraft\.(confirm|remove)\(/.test(click))return ()=>can(1,'generate_report');
 if(button.id==='accessConfirm'||/^JYAccess\.(pickTemplate|batchPermission)\(/.test(click))return ()=>JYAccess.admin();
 if(button.id==='workClosureConfirm')return ()=>can(1,/取消关闭/.test(document.getElementById('modal').textContent)?'reopen_order':'close_order');
 if(button.id==='salesClosureConfirm')return ()=>can(0,/取消关闭/.test(document.getElementById('modal').textContent)?'reopen_order':'close_order');
 return null;
}
function refresh(){
 for(const button of document.querySelectorAll('#app button,#modal button')){
  const check=rule(button),denied=!!check&&!check();
  if(denied){
   if(!locks.has(button))locks.set(button,{disabled:button.disabled,hidden:button.hidden,aria:button.getAttribute('aria-disabled')});
   if(!button.disabled)button.disabled=true;
   if(!button.classList.contains('permission-disabled'))button.classList.add('permission-disabled');
   if(button.getAttribute('aria-disabled')!=='true')button.setAttribute('aria-disabled','true');
   const hide=!button.hasAttribute('data-permission-visible');if(button.hidden!==hide)button.hidden=hide;
  }else if(locks.has(button)){
   const prior=locks.get(button);locks.delete(button);button.disabled=prior.disabled;button.hidden=prior.hidden;button.classList.remove('permission-disabled');
   if(prior.aria===null)button.removeAttribute('aria-disabled');else button.setAttribute('aria-disabled',prior.aria);
  }
 }
}
// Capture prevents stale buttons from running while permission/UI updates settle.
document.addEventListener('click',event=>{const button=event.target.closest?.('button');if(!button)return;const check=rule(button);if(check&&!check()){event.preventDefault();event.stopImmediatePropagation();refresh()}},true);
let queued=false;const schedule=()=>{if(queued)return;queued=true;queueMicrotask(()=>{queued=false;refresh()})};
const observer=new MutationObserver(records=>{for(const record of records){const button=record.target;if(record.attributeName==='disabled'&&locks.has(button)&&!button.disabled)locks.get(button).disabled=false}schedule()});
for(const id of ['app','modal'])observer.observe(document.getElementById(id),{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','hidden','data-permission-visible']});
window.JYPermissionButtons={refresh};window.addEventListener('focus',refresh);refresh();
})();
