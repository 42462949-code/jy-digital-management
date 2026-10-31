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
扫码页不再申请方向锁。手机横屏和竖屏均可扫码，旋转时保持摄像头流、已填字段与待补数量；横屏重排摄像头、工序/组别/备注、确认及操作栏。系统键盘弹起不当作设备旋转。离开扫码页停止并释放摄像头。

手机扫码界面紧凑调整（20261029-mobile23）：隐藏常驻提示、记录数和查询栏，三个操作按钮缩至28px高并放在摄像头右侧表单下方。手机扫码结果表体使用9pt字体，表头基础高度39px降为26px。电脑布局、全部原始数据与筛选功能保留；手机仍可使用表头箭头筛选，错误以临时提示显示。

手机横屏（20261029-rotate24）：非扫码页面随设备方向切换，横屏采用1440px桌面布局并按手机屏宽等比例适配；竖屏恢复普通响应式布局。保留原生双指缩放，不监听手势、不限制缩放倍数，不因键盘弹出或用户缩放重复重置视图。扫码报工使用原生手机视口及独立横竖屏布局，离开后恢复普通页面方向规则。手机系统自动旋转开关和浏览器自身的方向限制由设备控制。

手机扫码布局（20261029-scan25）：摄像头占左半屏，窗口保持3:5比例，预览视频保持原比例不拉伸；右侧工序、组别、备注等单列排列，操作按钮竖排。手机日期输入隐藏，扫码时自动取当天越南当地日期，避免长时间打开页面后继续使用昨天日期；电脑日期输入照常使用。小屏或软键盘打开时录入区域可单独滚动。

手机取景框进一步调整：预览改成居中正方形，裁掉原取景框上、下方多余画面，宽度约为屏幕的四分之三（比原半屏框放大约50%）；工序、组别和备注放在右侧，手动录入和操作按钮放在下方。手机摄像头解码使用与可见取景框一致的中央裁剪区域，电脑解码仍使用完整画面。

## 确认提交与勾选清除（20261029-confirm26）
扫码先保存为本机待提交草稿。用户核对后点“确认”，后台返回完整成功回执才标记已提交。断网、超时或后台未配置时保留待提交记录；每条记录使用持久化标识，防止回执丢失后重试重复入库。已提交记录不能在本机直接修改，清除操作不删除后台数据。有勾选项时可选择只清除勾选项或全部清除，清除前保存本机副本。

后台程序与部署说明在 [backend/README.md](backend/README.md)。当前未配置正式后台地址，前端会明确显示尚未上传；需要服务器或现有接口地址后才能接通真实后台。

手机扫码布局（20261029-layout27）：右侧工序、组别、备注输入与表体同为9pt；确认按钮移到备注下方，改为绿色72px正方形。底部保留启动、停止、清空和列设置，手机列设置使用适合触屏的卡片，可设列宽、顺序、显示与对齐，设置在当前浏览器自动保存并在下次进入恢复。桌面列设置照常可用；手机与电脑的浏览器设置不会自动跨设备同步。
按钮统一增加立体阴影、鼠标悬停凸起、按下凹陷和点击焦点效果；禁用状态不会凸起，表头筛选箭头继续保持无边框。

扫码结果状态列（20261029-status28）：勾选框后新增“状态”下拉列，草稿／已确认，新扫码默认草稿。状态作为独立核对元数据保存，原有10项扫码字段、后台接口和稳定记录ID保持不变。后台确认成功后状态自动变为已确认；手动选择已确认只表示核对，不会冒充后台上传成功，仍需点确认提交。已成功上传的记录不能改回草稿。原有扫码记录及列宽、顺序保留，仅在首次升级时把新增状态列插到最前面。

扫码结果新增“单位”列，默认在规格与数量之间，可按常规双击编辑；单位单独持久化并随确认提交传到后台。现有二维码仍为原五段格式，不含单位，因此默认留空，不猜测单位。新增列同样支持筛选、排序、导出、列设置和恢复记忆。

手机扫码退出（20261029-exit29）：新增居中“生产扫码报工”标题和右上角退出。手动录入字体与表体同为9pt，手机表头基础高度26px缩至18px。每次进入扫码页默认显示全部状态，不预设状态筛选；用户可手动筛选草稿或已确认记录。退出先等待本机数据保存，后台配置且登录后将全部记录及核对状态保存为退出快照；草稿不会因退出而自动变成已确认。后台失败可重试或明确选择仅本机退出；后台未连接时提示尚未上传。退出返回工作台，不退出账号。

手机表格可视高度修复：使用显式表格页类和浏览器实际 innerHeight 填满表格区域，不再依赖部分旧WebView不支持的 :has() 与 dvh；普通手机竖屏查询栏采用固定两行布局，避免查询按钮挤占字段。横屏仍按屏幕宽度等比例适配，允许原生双指缩放，扫码页使用独立横竖屏布局。

上述退出与手机表体高度调整一并在20261029-mobile30发布。正式后台地址仍未配置，未上传时会明确提示，并保存本机记录。

首页语言选择（20261029-language31）：中文／Tieng Viet 只在公司首页显示，工作台与各业务页不再重复显示。选择自动记在当前浏览器，登录、页面切换、弹窗和刷新后均沿用；业务记录及查询字段的内部标识保持原值，扫码状态下拉仅翻译选项文字，仍保存原中文枚举值。

横屏兼容（20261029-rotate32）：方向识别优先使用可视视口实际宽度（visualViewport.width × scale），避免内置浏览器方向属性过期，并且不把软键盘或双指缩放当作设备旋转；补充可视视口、方向媒体查询及延后复查事件。普通手机工作台提供“横屏查看”：支持时通过用户点击进入全屏并锁横屏，可恢复自动旋转；不支持时说明系统自动旋转和内置浏览器限制。进入扫码或首页会释放本功能取得的横屏锁。扫码页已改为支持横屏与竖屏。表头筛选箭头统一右移、下移至右下角，仍无边框。

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

- Normal phone pages use a fixed 65% initial scale in landscape, regardless of table width. The visible layout follows screen width while fixed-width tables scroll inside their own grid; saved column widths are not redistributed. Native pinch zoom remains unrestricted. Scanner supports both phone orientations using its native-scale responsive layout.
- Website icons now use only the transparent company symbol. `icons/company-symbol.ico` contains 16/24/32/48/64/128/256-pixel images; browser, manifest and Apple PNG icons retain alpha transparency. Manifest entries use `purpose: any` rather than the previous opaque maskable variants. Device launchers may still apply their own background or mask. Re-add existing shortcuts to refresh cached icon artwork.

### Scan landscape and header borders (2026-10-30)

Scan reporting no longer requests a portrait lock or displays a rotation-blocking overlay. Orientation changes reflow the native-scale mobile layout without stopping the active camera or canceling quantity entry. Other mobile tables retain their fixed 65% landscape scale. All business-grid header cells, including checkbox and information columns, use 1px white borders.

### Scan feedback and inactivity (2026-10-30)

- Valid, nonduplicate production QR reads play one short two-tone square-wave cue (2050/2750 Hz), before quantity completion or persistence. This indicates recognition, not backend submission. A reusable Web Audio context is unlocked by user gestures; desktop and mobile offer a sound preview. Audio errors never prevent recording, and the device's media volume remains under user control.
- Camera scanning stops after three minutes without a valid new QR read. Starting the camera or recognizing a valid code resets the timer; invalid codes and duplicate suppression do not extend it. Timer callbacks check the current camera generation and deadline so stopped or replaced sessions are not affected.
- Idle shutdown saves unsubmitted entries as local drafts through the existing queued/rollback-capable storage operation. Submitted entries keep their state and receipts. Pending quantity input remains open; finishing it still saves a draft. Failed saves are reported rather than claimed successful. Manual stop, exit and background camera release cancel the inactivity timer.

临时表上传核对（20261031-sync74）：按上传有效行（含未发货数量为0的行）的订单子表ID匹配销售订单，数量→订单数量、累计发货数量、未发货数量、预发货日期→客户交期、生产工艺以临时表为准；不新增未匹配销售订单。核对后销售订单未发货数量为0则状态改为“关闭”，业务筛选和下推兼容“关闭”与“已关闭”。临时表仍剔除零数量订单并整体替换、不备份；两表一起保存，失败时一起恢复。重复非空ID提示失败，空白ID不匹配。成功窗口显示匹配、修正字段、关闭及未匹配数量，确认后关闭。

临时表中转流程（20261031-transfer75，替代 sync74）：有效上传数据全部进入临时表中转，含零数量订单。按订单子表ID新增缺失销售订单（同名字段复制，数量→订单数量、预发货日期→客户交期、主计量单位→单位，其余字段留空）；已有ID只核对五个规定字段。核对后全部销售订单数值零余额统一关闭，最后清空临时表。两表同次保存且失败回滚，不产生旧数据备份。结果：读取=忽略+剔除空白ID+保留处理，原未匹配=新增+剔除空白ID；原已匹配不含新增。重复非空ID拒绝，重复上传不产生重复销售订单。

销售订单删除（20261031-delete76）：销售订单工具栏增加带悬停名称的删除图标，按左侧实际勾选的行删除，确认窗口显示数量。相同ID的其他未勾选行保留，其他业务表不变；仅清理已无保留行对应的信息录入元数据。等待本机保存完成后关闭窗口并更新表格，失败则恢复订单、信息和选择状态。删除至空表后刷新不自动载入发布样本。

现有销售订单一次性去重（20261031-dedupe77）：新版启动读取本机数据后执行，并在首次载入发布数据后补执行；按非空订单子表ID去除两端空白后比较，保留原始顺序中的第一条。保留空白ID行和剩余行关联的信息录入元数据，不改变其他表。保存完成后记录一次性完成标记，失败恢复原数据并允许刷新重试。需用户在保存业务数据的同一浏览器打开新版网址才能处理该浏览器的数据。

上传入口迁移（20261031-upload79）：销售订单列表工具栏原“导入EXCEL表”替换为“上传EXCEL表”，复用 transfer75 的23列上传文件和隐藏临时表中转流程，新增/五字段核对/零余额关闭/清空中转/确认结果不变。销售订单界面增加上传说明图标，成功后刷新销售列表并清除其查询、表头筛选与勾选，保留业务范围、列宽与查询列名。临时表数据槽、schema、设置及处理函数保留，只隐藏导航入口；其他表索引不变。

四组筛选框宽度（20261031-querywidth80）：每组右侧添加独立拖动边界，按表索引保存四个CSS像素宽度到 jy-query-widths-{index}，允许120–1600px；切换页面、刷新或重置查询后恢复设置，不改变表格列宽。首次拖动固定其余组当前宽度，避免其他组被重新分配；总宽度超过可用空间时筛选栏可左右滚动，小屏可换行。支持键盘左右键10px、Shift加左右键1px调整。保存失败恢复旧设置。与上传入口迁移一并发布。

筛选框左右独立宽度（20261031-queryparts81，替代 querywidth80 拖动方式）：四组各有左、右两个不可见边界拖动区，分别调整列名select与条件input的CSS像素宽度，另一侧宽度不变；无装饰竖线，仅调整光标和悬停说明。按表保存四组左右宽度到 jy-query-part-widths-{index}，每侧60–1600px。保留旧整组宽度作为未调整时的兼容布局，新调整后优先应用两侧宽度；切换、刷新和查询重置不丢失。

销售信息驱动标签（20261031-labelinfo83）：销售订单标签打印先用互斥模板选项选择模板，再读取全部销售订单信息录入列，不依赖行勾选或当前筛选。格式为张数、张数\数量、张数\数量\机台号、张数\\机台号；空白跳过，未赋值数量留空，不取订单总数。错误信息阻止整批生成并提示订单ID；每单张数/数量/机台号在预览中只读，打印总张数按每单累加，单次最多5000张。贴合模板原组别格显示机台号，泡棉模板订单号格另行显示机台号，河南模板公司区域显示机台号；纸张100×80mm、留白2mm及原表格边框不变。二维码仍为原五字段，空数量保留尾部分隔符。其他表的勾选打印保持原方式。编辑单元格2px，非编辑选中单元格1px。

生产班组与待确定工单（20261031-print85）：新增索引9生产班组表，六字段项次/部门/生产班组/班组负责人/描述/备注，复用主表筛选、建议、左右宽度、列设置、Excel编辑/导入导出，新增/勾选删除。销售下推先检查勾选，跳过已关闭/完成/已下达，选择贴合或泡棉及去重班组（每次下拉重新读取当前资料）。生成独立草稿，工单字段与明细表一致，Excel式编辑、粘贴、排序、拖行/上下移及撤销。草稿本机自动保存，正式表不提前写入；A4横向5mm页边距，thead重复标题和表头，底部制表人与越南时区当前打印时间。必须先打印最新修改版本，再明确点击确定才能写入正式工单并退出，失败回滚保留草稿；删除所有草稿行后可确定空单退出。打印机名称与制表人可保存修改；网页无法强制选择操作系统打印机或静默打印，系统打印窗口仍需选设备。
标签直接打印（print85）：模板选择窗口增加打印机名称并自动保存。点击打印按信息录入直接构建标签并调用系统打印，跳过编辑/预览界面。模板、打印机名记忆；四种录入规则、模板尺寸及2mm留白保持。浏览器无法按填写名称强制选设备，界面提供对应选择提示。

选中导航贴线（20261031-worktabs86）：当前表标签26px高、13px字号，未选标签保持20px；标签底部与顶栏分隔线贴齐，去掉下方额外留白，保留文字导航。worktabs86包含print85完整功能；A4工单thead/tfoot重复打印，每页保留标题、表头、制表与打印时间。


表格复制粘贴及手动扫码（20261031-sheet89）：所有业务明细表及待确定工单支持矩形选择、Shift扩选、Ctrl/Cmd+A、Ctrl/Cmd+C/V；工具栏复制和粘贴可用于触屏，浏览器禁止剪贴板读取时提供手动粘贴框。按当前筛选及显示列顺序操作，包含虚拟滚动未渲染的行；支持Excel的制表符、多行、引号及前导零。普通表末尾可追加粘贴行，待确定工单仅允许粘贴已有订单行；已提交扫码记录阻止整次粘贴，保存失败回滚。销售及工单的信息录入独立映射，不改变原始数组字段位置。

进入扫码页不请求摄像头，必须点击“启用摄像头”才开始；退出再进入仍不自动开始。待确定工单使用黑白表头、无勾选框或筛选箭头，拖列边界调整打印列宽并记忆；“打印”替代“A4打印”，“撤销”放弃整个待确定草稿并关闭，正式工单不写入。确认仍要求打印当前版本后明确点击“确定”。选中导航标签31px、未选28px，底部对齐分隔线。打印机名称仅保存作为选择提示，尚未接入本地打印程序，不能按名称自动选择系统打印机或静默打印。

打印机名称输入项移除（20261031-print90）：标签模板选择及待确定生产工单均移除打印机名称输入、名称必填验证及名称记忆提示。点击打印直接打开系统打印窗口选择设备；标签模板、制表人与其他设置继续保存。

生产工单参考版式（20261031-workformat91）：待确定编辑页与A4打印统一十列：项次、客户简称、订单号、客户指令单、品名及加工明细、代料品名、规格、订单数量、备注、ID。双语表头、蓝红标题、左侧生产机台、右侧红色下单日期、青绿色细表格线与参考列宽，正文顶端对齐并自动换行。正式工单原始字段全部保留，仅投影打印所需字段；旧草稿自动迁移版式并要求重新打印，新版列宽独立保存，继续支持编辑、排序、拖动行、复制粘贴和明确确认。

工单公司标志（20261031-worklogo92）：预览及打印页左上角加入现有佳洋公司LOGO，标题保持居中；打印等待标志图片加载完成，多页随顶端标题重复。

工单工具栏简化（20261031-worktools93）：移除待确定工单的复制、粘贴按钮，单元格区域仍支持Ctrl/Cmd+C和Ctrl/Cmd+V。

销售订单工单打印记录（20261031-worklog94）：待确定工单点击“确定”并成功保存正式工单时，按原始来源订单ID写入销售订单最后一列“工单已打印数”。格式为生产类型+确认当天日期（越南时区yyyy/M/d）+最终工单数量，每次另起一行追加保留原内容。来源ID单独记忆，不随临时编辑工单ID改变；旧草稿使用工单ID匹配。打印、撤销均不写入；订单缺失或ID重复拒绝整次确认，保存失败同时回滚工单、销售打印记录和草稿。
