/* Static homepage guide; business records and navigation are managed separately. */
(()=>{
 const tag=(title,text)=>`<li><h4>${title}</h4><p>${text}</p></li>`;
 const labelRule='结合照标标签打印规则，选择不同标签打印模板，一键多产品批量标签打印。标签模块可任意定制，包括生成二维码或条形码。';
 function render(){return `<section class="management-home-overview" aria-labelledby="management-guide-title">
  <div class="management-guide-intro">
   <p class="management-guide-eyebrow">内部数据化管理 · 使用指南</p>
   <h2 id="management-guide-title"><span>我们要在系统中做什么？</span><span>系统最后给我们输出什么？</span></h2>
   <div class="management-guide-rule" aria-hidden="true"></div>
  </div>
  <div class="management-guide-grid">
   <article class="management-guide-card" aria-labelledby="management-sales-title">
    <div class="management-guide-card-heading"><span class="management-guide-number" aria-hidden="true">01</span><h3 id="management-sales-title">销售订单管理</h3></div>
    <ol class="management-guide-steps">
     ${tag('更新销售订单','新接销售订单一键写入，自动更新原来订单状态（未发数为 0 的订单，状态自动调整为“关闭”），同步信息变更，如：工艺变更、订单数量变更、交期变更。')}
     ${tag('下推生成《生产工单》','依据销售订单下推生成《生产工单》，订单分批生产管理、工单打印。')}
     ${tag('打印标签',labelRule)}
     ${tag('订单关闭','系统中无效销售订单手工关闭。')}
    </ol>
   </article>
   <article class="management-guide-card" aria-labelledby="management-work-title">
    <div class="management-guide-card-heading"><span class="management-guide-number" aria-hidden="true">02</span><h3 id="management-work-title">生产工单管理</h3></div>
    <ol class="management-guide-steps">
     ${tag('生产报工','有两种方式：第一种是通过手工录入方式下推生成工序日生产报表；第二种是扫码报工，依据生产工单最后一列的二维码在系统中扫码报工。')}
     ${tag('打印标签',labelRule)}
     ${tag('生产进度自动更新','通过生产报表录入，自动更新工单已完工数据。')}
     ${tag('无效工单关闭','在生产工单明细表界面勾选生产工单，点“关闭”按钮即可关闭工单。工单关闭后不允许再做任何操作。')}
    </ol>
   </article>
   <article class="management-guide-card management-guide-attendance" aria-labelledby="management-attendance-title">
    <div class="management-guide-card-heading"><span class="management-guide-number" aria-hidden="true">03</span><h3 id="management-attendance-title">考勤管理</h3></div>
    <div class="management-guide-attendance-content">
     <div><h4>生产工时投入统计</h4><p>各班组负责人，每天提报当天本班组上班人数以及投入工时。投入工时按正常班工时、平时加班工时、周末加班工时分开统计；上班人数以早上上班开完早会后投入生产这时本班组的在职人数。</p></div>
     <div class="management-guide-reminder"><span>每日必报</span><p>基于人均小时产值统计，每天各班组要提交当天投入工时这一基础数据。</p></div>
    </div>
   </article>
   <article class="management-guide-card" aria-labelledby="management-stock-title">
    <div class="management-guide-card-heading"><span class="management-guide-number" aria-hidden="true">04</span><h3 id="management-stock-title">仓库管理</h3></div>
    <ol class="management-guide-steps">
     ${tag('仓库进销存台账','针对转仓棉、泡棉仓两个仓库做进销存管理台账。')}
     ${tag('即时库存查询','提供即时库存查询、导出业务。')}
     ${tag('盘点作业','账面结存导出生成《盘点表》，实盘数据录入后上传系统，自动生成盘点差异清单以及自动完成调账业务。')}
    </ol>
   </article>
   <article class="management-guide-card management-guide-output" aria-labelledby="management-output-title">
    <div class="management-guide-card-heading"><span class="management-guide-number" aria-hidden="true">05</span><h3 id="management-output-title">电子看板</h3></div>
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
