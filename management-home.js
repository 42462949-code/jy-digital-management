/* Static homepage guide; business records and navigation are managed separately. */
(()=>{
 const icons={sales:'<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M8 9h8M8 13h8M8 17h5"/>',work:'<path d="M3 21V10l6 3V7l6 3V3h4v18Z"/><path d="M6 17h1m4 0h1m4 0h1"/>',attendance:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',stock:'<path d="m3 8 9-5 9 5v12H3Z"/><path d="M7 20v-8h10v8M7 16h10M7 12l5 4 5-4"/>',output:'<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 22h8M12 18v4M7 14l4-4 3 2 4-5"/>'};
 const icon=kind=>`<svg class="management-guide-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[kind]}</svg>`;
 const modules=[['sales','01','销售订单管理'],['work','02','生产工单管理'],['attendance','03','考勤管理'],['stock','04','仓库管理'],['output','05','电子看板']];
 const heading=(kind,number,title,id)=>`<div class="management-guide-card-heading"><div class="management-guide-heading-icon">${icon(kind)}</div><h3 id="${id}">${title}</h3><span class="management-guide-number" aria-hidden="true">${number}</span></div>`;
 const tag=(title,text)=>`<li><h4>${title}</h4><p>${text}</p></li>`;
 const labelRule='结合照标标签打印规则，选择不同标签打印模板，一键多产品批量标签打印。标签模块可任意定制，包括生成二维码或条形码。';
 function render(){return `<section class="management-home-overview" aria-labelledby="management-guide-title">
  <div class="management-guide-intro">
   <div class="management-guide-intro-copy">
    <p class="management-guide-eyebrow"><span></span>内部数据化管理 · 使用指南</p>
    <h2 id="management-guide-title"><span>我们要在系统中做什么？</span><span>系统最后给我们<strong>输出什么？</strong></span></h2>
    <div class="management-guide-intro-tags" aria-hidden="true"><span>业务录入</span><i>→</i><span>流程管理</span><i>→</i><span>数据输出</span></div>
   </div>
   <div class="management-guide-visual" aria-hidden="true"><div class="management-guide-orbit orbit-one"></div><div class="management-guide-orbit orbit-two"></div><div class="management-guide-visual-core">${icon('output')}</div>${modules.map(([kind,n])=>`<div class="management-guide-visual-node visual-${kind}">${icon(kind)}</div>`).join('')}<div class="management-guide-visual-line"></div></div>
  </div>
  <div class="management-guide-index" aria-label="首页内容索引">${modules.map(([kind,n,label])=>`<a class="management-guide-index-item module-${kind}" href="#management-module-${kind}"><span class="management-guide-index-number">${n}</span><span>${label}</span>${icon(kind)}</a>`).join('')}</div>
  <div class="management-guide-grid">
   <article id="management-module-sales" class="management-guide-card module-sales" aria-labelledby="management-sales-title">
    ${heading('sales','01','销售订单管理','management-sales-title')}
    <ol class="management-guide-steps">
     ${tag('更新销售订单','新接销售订单一键写入，自动更新原来订单状态（未发数为 0 的订单，状态自动调整为“关闭”），同步信息变更，如：工艺变更、订单数量变更、交期变更。')}
     ${tag('下推生成《生产工单》','依据销售订单下推生成《生产工单》，订单分批生产管理、工单打印。')}
     ${tag('打印标签',labelRule)}
     ${tag('订单关闭','系统中无效销售订单手工关闭。')}
    </ol>
   </article>
   <article id="management-module-work" class="management-guide-card module-work" aria-labelledby="management-work-title">
    ${heading('work','02','生产工单管理','management-work-title')}
    <ol class="management-guide-steps">
     ${tag('生产报工','有两种方式：第一种是通过手工录入方式下推生成工序日生产报表；第二种是扫码报工，依据生产工单最后一列的二维码在系统中扫码报工。')}
     ${tag('打印标签',labelRule)}
     ${tag('生产进度自动更新','通过生产报表录入，自动更新工单已完工数据。')}
     ${tag('无效工单关闭','在生产工单明细表界面勾选生产工单，点“关闭”按钮即可关闭工单。工单关闭后不允许再做任何操作。')}
    </ol>
   </article>
   <article id="management-module-attendance" class="management-guide-card module-attendance management-guide-attendance" aria-labelledby="management-attendance-title">
    ${heading('attendance','03','考勤管理','management-attendance-title')}
    <div class="management-guide-attendance-content">
     <div><h4>生产工时投入统计</h4><p>各班组负责人，每天提报当天本班组上班人数以及投入工时。投入工时按正常班工时、平时加班工时、周末加班工时分开统计；上班人数以早上上班开完早会后投入生产这时本班组的在职人数。</p></div>
     <div class="management-guide-reminder"><span>每日必报</span><p>基于人均小时产值统计，每天各班组要提交当天投入工时这一基础数据。</p></div>
    </div>
   </article>
   <article id="management-module-stock" class="management-guide-card module-stock" aria-labelledby="management-stock-title">
    ${heading('stock','04','仓库管理','management-stock-title')}
    <ol class="management-guide-steps">
     ${tag('仓库进销存台账','针对转仓棉、泡棉仓两个仓库做进销存管理台账。')}
     ${tag('即时库存查询','提供即时库存查询、导出业务。')}
     ${tag('盘点作业','账面结存导出生成《盘点表》，实盘数据录入后上传系统，自动生成盘点差异清单以及自动完成调账业务。')}
    </ol>
   </article>
   <article id="management-module-output" class="management-guide-card module-output management-guide-output" aria-labelledby="management-output-title">
    ${heading('output','05','电子看板','management-output-title')}
    <p class="management-guide-output-intro">自动生成适时电子看板，如：</p>
    <ul class="management-guide-reports">
     <li>每天人均小时产值图表</li>
     <li>各工序每天产值图表</li>
     <li>每天销售额图表</li>
     <li>每天各工序投入工时图表</li>
     <li>未完结销售订单按客户分类统计订单金额等</li>
    </ul>
   </article>
  </div>
 </section>`}
 window.JYManagementHome={render};
})();
