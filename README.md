# JY数字化管理系统

独立的 GitHub Pages 部署，所有网页和资源直接位于此仓库根目录。

预期地址：https://42462949-code.github.io/jy-digital-management/

## 启用 Pages

GitHub Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: main → Folder: / (root) → Save。

不依赖原 `-ERP-` 仓库。首页可直接访问，不需要 ChatGPT 登录。

账号：admin；初始密码：888。密码修改、用户名记忆和业务数据保存在当前浏览器；这不是服务器端账号认证或多人共享数据库。

销售订单使用27列空模板。登录后点击“导入EXCEL表”读取本地文件，不把公司订单上传到公开仓库。

换设备或清理浏览器存储之前，请先导出Excel备份。

## 最新 Excel 模板

- 生产工单：14列，自动匹配 Sheet2。
- 各工序每日生产明细：17列，自动匹配 Sheet3。
- 临时表：23列，自动匹配“临时表”，不把合计与打印落款当作业务明细。

这三张表的导入会替换当前表明细，替换前保留本地副本；销售订单仍为追加导入。网站只发布列定义，业务记录需通过本地 Excel 导入，不写入公开仓库。生产图表按单位分别统计，生产数量空白时使用总码数。

## 经授权发布的正式数据

用户已明确授权将正式业务数据放入公开仓库。最新Excel数据以 gzip 压缩JSON发布，属于公开内容，任何人都可以下载解压；它不是加密文件。共有销售订单2303条、工单21条、生产明细5914条、临时表22286条。

首次使用时，空表会自动加载发布数据；已有非空表不会被覆盖。点击对应表的“恢复发布数据”，确认后可按最新Excel替换该表，原表会先保存一份本地副本。日常编辑仍只保存在当前浏览器，尚未提供多人共享写入。

临时表每次上传都替换本表旧明细（先备份），随后删除“未发货数量”为数值零的订单，识别 0、0.00 等格式。空白及非数字不作为零处理。取消选文件或校验失败时不改变原数据。上传后若全部为零则保存为空表，不会在下次打开时自动重新加载发布数据。

## 考勤表（最新模板）

考勤已改为按生产组别登记的10列工时成本表，公开的Excel为空白模板，保留21行供填写。原员工考勤示例在迁移前保存本地副本后移除。导入会自动匹配“考勤表”工作表并整体替换本表，导入空白模板可恢复空表；“确定”只保存当前数据，不向工时单价等业务字段写入确认文字。原表未给出计算公式，工时折算和成本字段保持可填写，不擅自假设加班倍率。


## 扫码报工（20261029-scan20）
导航“扫码报工”可启动手机后置摄像头，需在 HTTPS 页面允许相机权限。二维码格式为 `客户\客户指令单\品名及加工明细\规格\数量`（半角反斜杠）。数量空白或无效时先弹窗补填，取消不保存。工序、组别由操作员选择，日期默认越南当地日期，扫码时间按越南时区记录。扫码结果包含10列，可筛选、编辑、设定列和导出Excel。取景框内连续出现同一个码只记录一次，移开再扫描可继续报工；同一内容短时间重复提交会被拦截。离开界面或切到后台会释放摄像头。另支持二维码图片及手动粘贴。
扫码数据保存在当前设备浏览器的独立 IndexedDB，不自动同步其他手机或电脑。清空前保留本地副本 `jy-scan-before-clear`。既有七张业务表保留；新表使用独立槽位。二维码解码器 jsQR 为本地依赖，许可见 jsQR-LICENSE.txt。
临时表表体使用按单元格列宽自动缩小的字号，表头及其余表格保持原样；数据和导出内容不改变。

## 手机扫码布局（20261029-mobile22）
仅手机进入扫码报工时启用：扫码区域置顶，隐藏工作台顶部导航、图片识别、导出和列设置，保留启动摄像头、停止扫码和清空记录。表格与录入字段继续使用原有数据。电脑布局不变。
在支持 Screen Orientation API 的浏览器尝试锁定竖屏，不进入全屏或索取额外权限；不支持锁定时，横屏显示竖屏提示并暂停摄像头。转回竖屏会恢复原有字段和待补填数量，正常扫码时自动恢复摄像头。系统键盘弹起按设备方向判断，不会当作横屏。离开扫码界面恢复导航并释放本界面获取的方向锁。

手机扫码界面紧凑调整（20261029-mobile23）：隐藏常驻提示、记录数和查询栏，三个操作按钮缩至28px高并放在摄像头右侧表单下方。手机扫码结果表体使用9pt字体，表头基础高度39px降为26px。电脑布局、全部原始数据与筛选功能保留；手机仍可使用表头箭头筛选，错误以临时提示显示。

手机横屏（20261029-rotate24）：非扫码页面随设备方向切换，横屏采用1440px桌面布局并按手机屏宽等比例适配；竖屏恢复普通响应式布局。保留原生双指缩放，不监听手势、不限制缩放倍数，不因键盘弹出或用户缩放重复重置视图。扫码报工仍使用原生手机视口与竖屏限制，离开后恢复普通页面方向规则。手机系统自动旋转开关和浏览器自身的方向限制由设备控制。

手机扫码布局（20261029-scan25）：摄像头占左半屏，窗口保持3:5比例，预览视频保持原比例不拉伸；右侧工序、组别、备注等单列排列，操作按钮竖排。手机日期输入隐藏，扫码时自动取当天越南当地日期，避免长时间打开页面后继续使用昨天日期；电脑日期输入照常使用。小屏或软键盘打开时录入区域可单独滚动。

手机取景框进一步调整：预览改成居中正方形，裁掉原取景框上、下方多余画面，宽度约为屏幕的四分之三（比原半屏框放大约50%）；工序、组别和备注放在右侧，手动录入和操作按钮放在下方。手机摄像头解码使用与可见取景框一致的中央裁剪区域，电脑解码仍使用完整画面。

## 确认提交与勾选清除（20261029-confirm26）
扫码先保存为本机待提交草稿。用户核对后点“确认”，后台返回完整成功回执才标记已提交。断网、超时或后台未配置时保留待提交记录；每条记录使用持久化标识，防止回执丢失后重试重复入库。已提交记录不能在本机直接修改，清除操作不删除后台数据。有勾选项时可选择只清除勾选项或全部清除，清除前保存本机副本。

后台程序与部署说明在 [backend/README.md](backend/README.md)。当前未配置正式后台地址，前端会明确显示尚未上传；需要服务器或现有接口地址后才能接通真实后台。

手机扫码布局（20261029-layout27）：右侧工序、组别、备注输入与表体同为9pt；确认按钮移到备注下方，改为绿色72px正方形。底部保留启动、停止、清空和列设置，手机列设置使用适合触屏的卡片，可设列宽、顺序、显示与对齐，设置在当前浏览器自动保存并在下次进入恢复。桌面列设置照常可用；手机与电脑的浏览器设置不会自动跨设备同步。
按钮统一增加立体阴影、鼠标悬停凸起、按下凹陷和点击焦点效果；禁用状态不会凸起，表头筛选箭头继续保持无边框。

扫码结果状态列（20261029-status28）：勾选框后新增“状态”下拉列，草稿／已确认，新扫码默认草稿。状态作为独立核对元数据保存，原有10项扫码字段、后台接口和稳定记录ID保持不变。后台确认成功后状态自动变为已确认；手动选择已确认只表示核对，不会冒充后台上传成功，仍需点确认提交。已成功上传的记录不能改回草稿。原有扫码记录及列宽、顺序保留，仅在首次升级时把新增状态列插到最前面。

扫码结果新增“单位”列，默认在规格与数量之间，可按常规双击编辑；单位单独持久化并随确认提交传到后台。现有二维码仍为原五段格式，不含单位，因此默认留空，不猜测单位。新增列同样支持筛选、排序、导出、列设置和恢复记忆。

手机扫码退出（20261029-exit29）：新增居中“生产扫码报工”标题和右上角退出。手动录入字体与表体同为9pt，手机表头基础高度26px缩至18px。每次进入扫码页默认按草稿筛选，已确认记录只隐藏而不删除，可用状态列筛选查看。退出先等待本机数据保存，后台配置且登录后将全部记录及核对状态保存为退出快照；草稿不会因退出而自动变成已确认。后台失败可重试或明确选择仅本机退出；后台未连接时提示尚未上传。退出返回工作台，不退出账号。

手机表格可视高度修复：使用显式表格页类和浏览器实际 innerHeight 填满表格区域，不再依赖部分旧WebView不支持的 :has() 与 dvh；普通手机竖屏查询栏采用固定两行布局，避免查询按钮挤占字段。横屏仍按屏幕宽度等比例适配，允许原生双指缩放，扫码页维持竖屏专用规则。

上述退出与手机表体高度调整一并在20261029-mobile30发布。正式后台地址仍未配置，未上传时会明确提示，并保存本机记录。

首页语言选择（20261029-language31）：中文／Tieng Viet 只在公司首页显示，工作台与各业务页不再重复显示。选择自动记在当前浏览器，登录、页面切换、弹窗和刷新后均沿用；业务记录及查询字段的内部标识保持原值，扫码状态下拉仅翻译选项文字，仍保存原中文枚举值。

横屏兼容（20261029-rotate32）：方向识别优先使用可视视口实际宽度（visualViewport.width × scale），避免内置浏览器方向属性过期，并且不把软键盘或双指缩放当作设备旋转；补充可视视口、方向媒体查询及延后复查事件。普通手机工作台提供“横屏查看”：支持时通过用户点击进入全屏并锁横屏，可恢复自动旋转；不支持时说明系统自动旋转和内置浏览器限制。进入扫码或首页会释放本功能取得的横屏锁。扫码页继续仅竖屏。表头筛选箭头统一右移、下移至右下角，仍无边框。

工作台公司标志移除外框，图标与系统名称放大；中文名称按用户指定改为“佳洋数字化管理系统”。

添加到手机桌面（20261029-icon34）：使用完整佳洋 Jiayang 公司标志，提供Android 192/512px普通与maskable图标、iOS 180px Apple Touch Icon及浏览器备用图标。图标由现有公司SVG等比例渲染，白底无边框；maskable内容在安全圆内，避免手机裁切字样。manifest路径、作用域与启动地址均限制在独立仓库路径，竖横屏规则不作全局锁定。旧桌面快捷方式可能缓存图标，不一定立即刷新；请从新版页面添加并先保留原入口。本次更新不修改业务数据。未新增离线缓存或服务工作线程。

列宽和登录界面（20261029-layout35）：列宽按保存像素值固定，表格不按手机屏宽重新分配列宽；普通手机横屏按整张表总宽度（至少1440px）缩放整个界面，保留手势缩放。触屏浏览不再意外拖动列边缘修改宽度，仍可在列设置调整。电脑和手机的本机设置不会自动共享，新增列设置JSON导出／导入用于跨设备沿用；自动跨设备同步仍需要共享后台。首页语言、图片切换和登录类弹窗按钮恢复平面效果；登录框收窄，标题放大，用户名和密码使用图标与无障碍隐藏标签。

手机端隐藏业务Excel导入／上传、导出、标签打印和打印按钮（横屏亦隐藏），电脑保留；列设置文件的跨设备导入／导出入口仍可使用。“恢复发布数据”和“更新”工具栏按钮已移除。首页语言、工厂图片切换及登录弹窗按钮改为平面，登录标题居中。

### Label templates and cell entry (2026-10-30)

- Label printing offers lamination, foam and Henan customer templates. Each page is 100 × 80 mm, with 2 mm internal margins. Preview edits and copy counts affect printing only; source business records are unchanged. Use actual size and disable browser headers/footers. Physical feed gaps are configured in the printer driver.
- Henan QR payload follows the five-field production-scanning backslash format, including an empty final quantity. Code 128B packaging barcodes accept printable ASCII. QR encoder dependencies and licenses are bundled locally in `qr-encoder.js` and `qr-encoder-LICENSE.txt`.
- Production work orders project an editable `信息录入` column before `工单下达日期`. Its values are stored by `workOrderIdentity` in `jy-work-information`. Original 14-field work-order arrays stay unchanged so existing production/scanner mappings remain compatible. Legacy 14-column Excel imports remain valid; optional information values are included on export/import.
- Business cells use click-to-select, double-click/F2-to-edit, type-to-replace, Escape-to-cancel, Enter-to-save-and-move, and Tab navigation. Submitted scan records remain protected by the existing edit checks.

Sales orders also project `信息录入` before `状态`, saved independently in `jy-sales-information` by original order-line ID. Both original sales/work Excel layouts remain importable; optional information values round-trip as the first exported column. Date formatting, labels, business status/process filters and downstream work/report mappings continue to use the original source fields.

### Readable landscape and transparent shortcuts (2026-10-30)

- Normal phone pages use at least 50% automatic initial scale in landscape. The visible layout follows screen width while fixed-width tables scroll inside their own grid; saved column widths are not redistributed. Native pinch zoom remains unrestricted. Scanner portrait rules are unchanged.
- Website icons now use only the transparent company symbol. `icons/company-symbol.ico` contains 16/24/32/48/64/128/256-pixel images; browser, manifest and Apple PNG icons retain alpha transparency. Manifest entries use `purpose: any` rather than the previous opaque maskable variants. Device launchers may still apply their own background or mask. Re-add existing shortcuts to refresh cached icon artwork.
