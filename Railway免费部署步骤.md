# Railway Free 部署 ChemCritic

本副本保留最终版前端、提示词与实验判定功能，仅增加云端入口及部署文件。不要把 SciencePal 密钥或网站密码写进 GitHub。

## 1. 注册与确认免费额度

访问 https://railway.com/ ，使用 GitHub 登录并连接账号。
当前官方规则：新用户试用最多30天或一次性5美元额度；之后 Free 每月1美元额度，不结转。
在账户套餐页面确认当前为 Trial / Free，不需要为了本教程主动升级到付费方案。
若显示 Limited Trial，出站网络受限，可能无法访问 SciencePal；GitHub验证能否通过由平台决定，不能通过代码绕过。
参考 https://docs.railway.com/pricing/free-trial

## 2. 上传这个副本

将本文件所在 ChemCritic 目录的内容上传至 GitHub 私有仓库根目录。
根目录应直接包含 Dockerfile、railway.toml、requirements.txt、app、cases、deployment、tools。
不要只上传ZIP，也不要套多余的外层目录。现有最终版代码若已上传，只合入本副本的新增及修改文件即可，不要覆盖回旧提示词。

## 3. Railway 创建项目

选择 New Project → Deploy from GitHub repo，授权并选择仓库。
程序按根目录 Dockerfile 构建，启动命令在镜像中，无需填本机 server --sciencepal 命令。
首次自动部署若因缺少配置失败，先按下面步骤配置，再重新部署，不需要重复创建服务。

## 4. 配置 Variables

在服务的 Variables 中添加：

| 名称 | 由使用者填写的内容 |
| --- | --- |
| SCIENCEPAL_API_KEY | 有效的 SciencePal API Key，仅填密钥本身 |
| DEMO_USER | 自定的网站登录用户名 |
| DEMO_PASSWORD | 自定的网站密码，至少16个字符；不是SciencePal密钥 |
| PORT | 8080 |
| DATA_DIR | /data |

不要把变量的真实内容提交仓库、截图或发给他人。网站登录密码只分享给你授权的访问者。

## 5. 生成网址

进入服务 Settings → Networking / Public Networking → Generate Domain，目标端口填写8080。
Railway 提供 RAILWAY_PUBLIC_DOMAIN 时，程序会自动使用 https:// 加该域名。
若启动仍提示缺少云配置，手动新增 PUBLIC_ORIGIN，值为刚生成的完整 https://网址，末尾不带路径，再部署。
不要把浏览器本机的127.0.0.1地址填入此处。

## 6. 保存历史记录

为该服务添加 Volume，挂载路径填写 /data，与 DATA_DIR 保持一致。
当前官方 Free 默认0.5GB、最多1个卷，Trial默认0.5GB、最多3个卷；以账户实际显示为准。存储也计入资源用量。
参考 https://docs.railway.com/volumes/reference
数据库位于 /data/chemcritic.sqlite3。若不挂卷，历史记录不能保证在重启、重新部署后保留。
数据卷保存的是历史记录，不是正在执行的 Agent 内存任务。

## 7. 部署与验证

应用配置后点击 Deploy / Redeploy。若有 Root Directory 配置，保持仓库根目录。
成功后访问生成的网址，浏览器会提示登录，填写 DEMO_USER 和 DEMO_PASSWORD。
先检查页面能打开、能填写实验记录，再由使用者手动提交一个模拟案例，确认 Agent 返回。
/healthz 返回200仅代表进程健康，不代表 SciencePal 密钥有效或科学结果通过核验。
SciencePal Agent列表HTTP401：检查该平台 Variables 内的SCIENCEPAL_API_KEY，修改后重新部署。
打开首页HTTP401：先完成网站用户名与密码登录，这是不同的验证。
若首页能开但Agent网络失败，检查账号是否Limited Trial、SciencePal可用性及部署日志；不要反复提交创建新任务。

## 8. 免费使用与边界

查看 Usage / Estimated Usage，1美元额度不保证整月不休眠运行，SciencePal仍使用你自己的额度。
初次调试与正在执行任务期间保持 Serverless/App Sleeping 关闭。开启休眠可以减少闲置资源消耗，但唤醒或重启后本地内存任务可能丢失；不要把开启休眠当作无影响的配置。
本副本沿用现有单实例、任务内存记录及串行提交限制，不新增多人账号隔离；共用网站账号的访问者共享历史。适合共享演示入口，不能宣称是独立用户数据隔离的公共服务。
及时导出 Agent 结果。平台免费额度、资源限制和数据保留规则可能变化，以控制台和官方文档为准。

本地已验证配置、认证、同源访问、限流与原有测试；未在Railway构建镜像，未创建在线服务，未使用任何真实密钥调用SciencePal。
