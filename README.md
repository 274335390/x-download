# 东东下载 Dongdong 0.1.1

免费 X / Twitter 媒体下载器：一套 HTML 界面，同时用于网页版和 Windows 桌面版。所有下载功能免费，支持作者完全自愿。

在线使用：[x.dd-oss.com](https://x.dd-oss.com/)。Windows 版可从网站顶部的 Windows 入口下载。

## Windows 使用

双击 `Dongdong.exe` 打开独立窗口，无需安装 Python、Node.js 或 FFmpeg。Windows 10/11 x64，需要 Microsoft Edge WebView2 Runtime（多数较新 Windows 已安装）。如缺少 WebView2，可运行 `start-web.bat` 使用浏览器界面，或安装微软官方 WebView2 Runtime。

1. 复制 X 帖子的链接，粘贴后点击“解析下载”。
2. 在弹窗中选择画质、原图、GIF 或 MP3；多文件可打包为 ZIP。
3. 桌面版选择保存位置；网页版通过浏览器保存。进度直接显示在所点的下载按钮上，失败可原位重试；不另列下载记录。

网页版及 Windows 窗口内容使用同一套浅色 / 深色界面，自动跟随系统或浏览器的颜色偏好，切换时无需刷新。

页面提供三步操作示意图。右上角可切换 30 种语言，涵盖操作界面、下载状态、错误提示、帮助和法律说明。简繁中文、英语、日语、韩语、西班牙语、葡萄牙语、法语、德语、意大利语、荷兰语、俄语、乌克兰语、越南语、印尼语、马来语、土耳其语、波兰语、捷克语、罗马尼亚语、匈牙利语、阿拉伯语、希伯来语、波斯语、希腊语、泰语、印地语、挪威语、瑞典语和芬兰语。首次使用按浏览器语言选择；手动选择保存在本地，帖子原文不翻译。翻译尚未经过母语审校。

Windows 版为未签名的本地构建，只提供手动检查更新，不会自动下载、安装或强制更新。首次启动单文件 EXE 会解包内置运行时，可能需要几秒钟。

## HTML / 网页版

双击 `start-web.bat`，然后访问 `http://127.0.0.1:18765`。网页版和桌面版拥有相同功能。

`web/index.html` 配合同目录的 `style.css`、`app.js`、`i18n.js` 构成网页界面。请保留整个 `web/` 目录。**实际解析、下载和转码需要运行配套后端；把 HTML 单独放到静态托管上不能完成下载。**

源码运行（Python 3.10+）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --web
```

源码运行时，MP3 / GIF 转换需要系统 PATH 中的 FFmpeg，或将实际的 `ffmpeg.exe` 放进 `vendor/`。打包的 Windows EXE 已内置 FFmpeg。

仅启动服务、不打开浏览器：

```powershell
.\.venv\Scripts\python.exe app.py --web --no-browser --port 18765
```

源码桌面模式需安装 `requirements-desktop.txt`，再运行 `python app.py`。

## 支持范围

- 视频：原始 MP4，选择上游提供的清晰度，多视频帖子可逐个下载或自动打包。
- 照片：原图；同一帖子多张照片可打包 ZIP。
- GIF：X 通常存储为 MP4，支持下载该原始动图，也支持实际转为 `.gif`。GIF 输出为 640 像素宽 / 12 fps / 128 色，最多转换前 120 秒；完整动图可保存为原始 MP4。
- MP3：从带音轨的视频提取。没有音轨的资源会明确提示，不能凭空生成音频。
- 界面包含常见问题、“关于 / 服务条款 / 隐私政策 / 免责声明”。内容按本地预览版实际数据处理方式编写；公开运营前需补充运营主体、有效反馈渠道和实际托管日志策略。
- 单次下载（含 ZIP）上限 256 MB，最多同时处理 2 个下载。解析和任务元数据仅保留在内存中，约 30 分钟过期；不保留媒体结果缓存。

接口提供作者头像时显示真实头像，缺失或加载失败时只保留作者名。

只处理输入帖子的直接媒体，不递归下载引用帖、直播或整个账号。不支持私密、已删除或需要登录授权的内容。解析依赖第三方 FxEmbed 公共 API，失败后尝试 yt-dlp 视频解析；上游接口变化、限流或网络不可达时可能失败，照片解析目前依赖 FxEmbed。

应用没有登录、广告、付费墙、跟踪脚本或下载历史数据库。解析时会将帖子 ID 提交给 FxEmbed；下载访问 X 媒体 CDN。

后端以流式方式传输媒体，ZIP 直接输出数据流，FFmpeg 从媒体 CDN 读取并通过标准输出管道生成 GIF / MP3；不主动在磁盘创建媒体临时文件。Waitress 的响应缓冲限制在内存中，禁止溢出落盘。网页版使用浏览器侧 Blob 接收再保存，较大文件会占用较多浏览器内存，浏览器仍可能使用自己的磁盘缓存或 `.crdownload`；这不受本应用控制。Windows 版直接写入用户选择的最终路径，遇到已有文件要求改名，失败时尝试删除本次创建的不完整文件。单文件 EXE 解包的运行时不是媒体缓存。

## 检查更新（仅 Windows 桌面版）

在“关于”里点击“检查更新”，软件才会请求版本信息。网页版不显示检查按钮和版本号；桌面版在“关于”标题和页脚显示版本号。发现新版后提供发布页链接，由用户自行下载；没有后台检查、自动安装或强制更新。

EXE 同级的 `updates.json` 配置更新来源，内置同一份默认配置：

- `manifest_url`：官网的 HTTPS 版本清单地址。当前留空，取得域名后填写。
- `github_repo`：`274335390/x-download`，官网未配置或请求失败时读取此仓库的 GitHub Releases。
- `tag_prefix`：`v`，只识别本项目的正式发布。

GitHub 版本标签使用 `v0.1.1` 这样的格式，并附上 `Dongdong.exe` 或 `Dongdong-Windows.zip`。草稿、预发布及没有桌面附件的 Release 不视为可更新版本。没有匹配的发布时会明确显示“暂未发布桌面版更新”，网络错误不会被当作“已是最新版”。版本使用三段数字，按数字比较。

官网清单字段为 `version`（例如 `0.1.1`）和 `url`（真实的 HTTPS 下载页）。只请求版本信息，不向更新服务上传帖子链接或下载记录。后续正式发布前，请同步审查第三方二进制分发要求。

## 支持项目

应用内不设置打赏入口。打赏方式确定后仅在本仓库公布，目前尚未配置收款码。

## 网络与代理

运行后端的电脑必须能够访问 FxEmbed、X 和 `*.twimg.com`。Requests 会使用其支持的系统 / 环境代理。可显式指定 HTTP 或 HTTPS 代理：

```powershell
.\.venv\Scripts\python.exe app.py --web --proxy http://127.0.0.1:7890
```

也可设置 `DONGDONG_PROXY`（兼容旧的 `XDOWNLOAD_PROXY`） 环境变量。Windows 单文件同样接受这些命令行参数。此版本没有附带代理服务。

## Windows 打包

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
powershell -ExecutionPolicy Bypass -File build.ps1 -FFmpegPath C:\path\to\ffmpeg.exe
```

产物：`release/current/Dongdong.exe`，附带网页启动脚本、说明和第三方许可文件。编译环境需 Windows x64。打包不会修改系统 PATH。

## 部署成网站

前端和后端部署在同一站点。GitHub Pages 只能托管静态文件，不能运行解析、下载或转码；HTTPS 网页也不能直接调用 HTTP 后端。建议使用服务器上的同源 HTTPS 反向代理。

Linux 部署配置见 `deploy/x-download.service` 和 `deploy/nginx.conf.example`。源码放在 `/opt/x-download/current`，Python 虚拟环境放在 `/opt/x-download/venv`；用虚拟环境中的 pip 安装 `requirements.txt`。FFmpeg 可使用系统已有版本，或放在 `/opt/x-download/bin/ffmpeg`，不必替换系统版本。部署到已有项目的服务器时，使用独立目录和用户，不升级其他项目依赖。

```sh
/opt/x-download/venv/bin/python /opt/x-download/current/app.py --web --no-browser --host 127.0.0.1 --port 18765 --production
```

`--production` 关闭本地诊断信息，适用于反向代理后的服务。程序使用 Waitress。systemd 配置以 `xdownload` 用户运行，限制 CPU 为一个核心、内存为 512 MB，并降低 CPU 调度优先级。使用配置前需创建该系统用户，确认端口空闲；将服务文件放入 `/etc/systemd/system/` 后只启用 `x-download.service`。

没有域名时保持监听 `127.0.0.1`，通过 SSH 转发预览，不开放应用端口。有域名后，复制 Nginx 示例为独立站点，替换 `server_name`，配置 HTTPS，再检查配置并平滑重载；保留已有站点配置。示例关闭代理响应缓冲和缓存、限制解析请求与下载并发，避免代理把媒体缓冲到磁盘。CDN 也应关闭下载路由缓存。公网使用需按服务器容量设置带宽额度；当前是单进程小规模版本。

需要网页提供 Windows 下载时，把 EXE 放在源码目录的 `release/current/Dongdong.exe`。服务器部署不需要安装桌面依赖或 WebView2。

本站 HTTPS 使用免费的 Let's Encrypt 证书。Certbot 通过 `webroot` 验证 `/var/lib/x-download-acme`，Nginx 在 HTTP 站点中保留 `/.well-known/acme-challenge/` 路径，其余 HTTP 请求跳转到 HTTPS。`certbot.timer` 定期检查并在到期前续期；续期成功后执行项目专用 hook，先检查 Nginx 配置，再平滑加载新证书。

服务器上的独立站点配置为 `/etc/nginx/sites-available/x-download`，续期 hook 为 `/etc/letsencrypt/renewal-hooks/deploy/x-download.sh`。维护时保留域名 A 记录和公网 80 / 443 端口，勿删除验证路径或停用计时器。查看续期任务可运行 `systemctl list-timers certbot.timer`；使用 Certbot 自带的模拟续期命令 `certbot renew --cert-name x.dd-oss.com --dry-run --run-deploy-hooks --no-random-sleep-on-renew` 检查续期及加载流程。无需在域名注册商购买 SSL。

品牌资源位于 `web/brand.svg`、`web/brand.png` 和 `web/brand.ico`。名称尚未经过商标检索，公开发布前需确认目标地区的品牌使用条件。

免责声明提醒个人学习、研究或欣赏仍须有合法依据；免费和自愿打赏不代表自动获得授权。公开运营前需补全真实主体及可用投诉渠道，并按实际运营地区审查条款。

基础语法、构建和实际操作验证记录会随交付说明给出。本项目未新增测试代码。

第三方依赖和许可证见 `THIRD_PARTY.md`。


## 源码许可

本项目自有源码采用 MIT 许可证，见 `LICENSE`。第三方组件、媒体内容及相关标志不因此改变许可或权利归属，详见 `THIRD_PARTY.md`。独立仓库：[274335390/x-download](https://github.com/274335390/x-download)。
