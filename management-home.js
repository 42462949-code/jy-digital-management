/* Static homepage guide; business records and navigation are managed separately. */
(()=>{
 const icons={sales:'<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M8 9h8M8 13h8M8 17h5"/>',work:'<path d="M3 21V10l6 3V7l6 3V3h4v18Z"/><path d="M6 17h1m4 0h1m4 0h1"/>',attendance:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',stock:'<path d="m3 8 9-5 9 5v12H3Z"/><path d="M7 20v-8h10v8M7 16h10M7 12l5 4 5-4"/>',output:'<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 22h8M12 18v4M7 14l4-4 3 2 4-5"/>'};
 const icon=kind=>`<svg class="management-guide-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[kind]}</svg>`;
 const heading=(kind,number,title,id)=>`<div class="management-guide-card-heading"><div class="management-guide-heading-icon">${icon(kind)}</div><h3 id="${id}">${title}</h3><span class="management-guide-number" aria-hidden="true">${number}</span></div>`;
 const tag=(title,text)=>`<li><h4>${title}</h4><p>${text}</p></li>`;
 const labelRule='结合标签打印规则，可选择不同模板，实现多产品标签一键批量打印；模板支持自定义，并可生成二维码或条形码。';
 function render(){return `<section class="management-home-overview" aria-labelledby="management-guide-title management-output-question">
 <div class="management-overview-columns">
  <div class="management-input-panel">
   <div class="management-guide-intro"><div class="management-guide-intro-copy"><h2 id="management-guide-title">我们要在系统中做什么？</h2></div></div>
   <div class="management-guide-grid">
<article id="management-module-sales" class="management-guide-card module-sales" aria-labelledby="management-sales-title">
    ${heading('sales','01','销售订单管理','management-sales-title')}
    <ol class="management-guide-steps">
     ${tag('更新销售订单','支持新接销售订单一键上传，自动更新原订单状态（未发货数量为 0 时自动调整为“关闭”），并同步工艺、订单数量、交期等信息变更。')}
     ${tag('下推生成《生产工单》','依据销售订单下推生成《生产工单》，支持订单分批生产管理及工单打印。')}
     ${tag('打印标签',labelRule)}
     ${tag('订单关闭','系统中的无效销售订单支持手工关闭。')}
    </ol>
   </article>
<article id="management-module-work" class="management-guide-card module-work" aria-labelledby="management-work-title">
    ${heading('work','02','生产工单管理','management-work-title')}
    <ol class="management-guide-steps">
     ${tag('生产报工','支持两种方式：手工录入并下推生成工序日生产报表；扫描生产工单最后一列的二维码，在系统中完成扫码报工。')}
     ${tag('打印标签',labelRule)}
     ${tag('生产进度自动更新','根据生产报表录入的数据，自动更新工单已完工数据。')}
     ${tag('无效工单关闭','在生产工单明细表中勾选工单，点击“关闭”即可关闭工单；工单关闭后，不允许再进行任何操作。')}
    </ol>
   </article>
<article id="management-module-attendance" class="management-guide-card module-attendance management-guide-attendance" aria-labelledby="management-attendance-title">
    ${heading('attendance','03','考勤管理','management-attendance-title')}
    <div class="management-guide-attendance-content">
     <div><h4>生产工时投入统计</h4><p>各班组负责人须每日提报本班组当天的上班人数及投入工时。投入工时按“正常班工时、平时加班工时、周末加班工时”分类统计；上班人数以早会结束后、正式投入生产时本班组的在职人数为准。</p></div>
     <div class="management-guide-reminder"><span>每日必报</span><p>为满足人均小时产值统计需要，各班组须每日提交当天投入工时这一基础数据。</p></div>
    </div>
   </article>
<article id="management-module-stock" class="management-guide-card module-stock" aria-labelledby="management-stock-title">
    ${heading('stock','04','仓库管理','management-stock-title')}
    <ol class="management-guide-steps">
     ${tag('仓库进销存台账','针对转仓棉、泡棉仓两个仓库建立进销存管理台账。')}
     ${tag('即时库存查询','提供即时库存查询及数据导出功能。')}
     ${tag('盘点作业','导出账面结存数据生成《盘点表》；录入并上传实盘数据后，系统自动生成盘点差异清单，并自动完成调账业务。')}
    </ol>
   </article>
   </div>
  </div>
  <div class="management-output-panel">
   <div class="management-guide-intro management-output-question"><div class="management-guide-intro-copy"><h2 id="management-output-question">系统最后给我们<strong>输出什么？</strong></h2></div></div>
<article id="management-module-output" class="management-guide-card module-output management-guide-output" aria-labelledby="management-output-title">
    ${heading('output','05','电子看板','management-output-title')}
    <p class="management-guide-output-intro">自动生成实时电子看板，包括：</p>
    <ul class="management-guide-reports">
     <li>每日人均小时产值图表</li>
     <li>各工序每日产值图表</li>
     <li>每日销售额图表</li>
     <li>每日各工序投入工时图表</li>
     <li>按客户分类统计未完结销售订单金额等</li>
    </ul>
   </article>
  </div>
 </div>
 </section>`}
 function fit(){const root=document.querySelector('.management-home-overview');if(!root)return;root.style.zoom='';root.style.width='';root.style.maxWidth='';if(innerWidth<1000||document.documentElement.classList.contains('phone-device'))return;const available=innerHeight-root.getBoundingClientRect().top-2,natural=root.getBoundingClientRect().height;if(available<=0||natural<=available)return;let scale=available/natural;const apply=()=>{root.style.zoom=String(scale);root.style.width='100%';root.style.maxWidth='none'};apply();const actual=root.getBoundingClientRect().height;if(actual>available){scale*=available/actual;apply()}}
 window.addEventListener('resize',()=>requestAnimationFrame(fit));
 window.JYManagementHome={render,fit};
})();
