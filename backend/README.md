# 扫码报工后台

这是独立 API 程序，需要部署到真实服务器；GitHub Pages 只提供静态网页，不能运行此后台。当前线上 `backend-config.js` 的 `baseUrl` 留空，确认按钮会说明尚未上传，并保留本机草稿。

## 部署

1. 准备一个指向服务器的域名，开放80和443端口，安装 Docker Compose。
2. 把本目录放到服务器，在同目录创建 `.env`，设置 `JY_API_DOMAIN`、`JY_ADMIN_USER` 和至少8字符的 `JY_ADMIN_PASSWORD`。密码只留在服务器，不提交到仓库。
3. 执行 `docker compose up -d --build`。Caddy 为域名提供HTTPS，SQLite数据库放在持久卷 `reports`，请定期备份该卷。
4. 检查 `https://你的域名/api/health` 返回 `{"ok":true}`。
5. 将网站根目录 `backend-config.js` 中的 `baseUrl` 设置为 `https://你的域名`（不带 `/api`），发布前端。

后台账号与目前仅保存在浏览器的工作台账号独立。第一次确认提交时登录报工后台；凭证只发送到配置的HTTPS服务，访问令牌保存在当前标签页会话，不写入源码或公开仓库。修改后台密码需要更新服务器环境变量并重启，现存会话会失效。

## 接口

- `POST /api/login`：`{username,password}` → `{token,expiresAt}`。
- `POST /api/scan-reports`：Bearer令牌，`{batchId,records:[{id,values:[十个字段]}]}` → `{batchId,acceptedIds,receivedAt}`。每次1–200条，全部验证后原子入库；同一记录ID重复重试不重复入库，已有ID携带不同内容返回409。
- `GET /api/scan-reports?limit=200&offset=0`：Bearer令牌，分页查看后台记录及字段顺序。
- `GET /api/health`：服务存活检查，不返回业务数据。

字段顺序：扫码时间、日期、工序、组别、客户、客户指令单、品名及加工明细、规格、数量、备注。扫码时间为越南当地时间字符串，后台另存UTC接收时间和登录账号。

默认允许网页来源 `https://42462949-code.github.io`，可通过服务器环境变量 `JY_ALLOWED_ORIGINS` 调整；不要把仓库路径写入来源。未认证不能读写业务数据。清除手机记录只清除本机副本，后台已提交记录保留。

## 本机验证

仅限开发，可用 `JY_DB_PATH` 指向临时文件，设置测试账号环境变量后运行 `python server.py`，前端地址使用 `http://127.0.0.1:8000`。正式使用需要HTTPS。程序只依赖Python标准库。

单位扩展：记录可带可选字符串 `unit`（最多80字符），不改变 `values` 的10项顺序；后台单独持久化单位，查询记录会带回该属性。兼容未带单位的旧提交，已有数据库会补建单位列。状态是前端核对元数据，不作为已入库证明。

退出快照：`POST /api/scan-checkpoints` 需要Bearer令牌，接收 `{checkpointId,deviceId,partIndex,totalParts,records}`；每片最多200条，records包含既有字段及 `reviewStatus`、`submittedAt`。只在全部分片保存后返回 `complete:true`。这保存草稿和核对状态，不把草稿当作正式已确认报工。`GET /api/scan-checkpoints/latest?deviceId=...` 返回该账号该设备最近一次完整快照；未完成快照不作为恢复依据。正式确认仍用 `/api/scan-reports`。
