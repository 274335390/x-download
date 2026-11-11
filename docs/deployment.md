# 部署说明

## Linux 服务

前后端部署在同一个站点。默认 `XDOWNLOAD_WEB_PROCESSING=browser`：Python 后端解析 X / Instagram 帖子，用户浏览器直连对应平台的媒体 CDN，下载、ZIP 和格式转换在用户设备处理。用户网络需能访问 X 的 `video.twimg.com` / `pbs.twimg.com` 或 Instagram 的 `cdninstagram.com` / `fbcdn.net` 下媒体节点；响应也必须允许跨域读取。失败只提示，不自动回退服务器。

部署前执行 `python scripts/fetch-browser-vendor.py`，从官方 npm 源恢复固定版本依赖；也可在开发电脑执行后将生成的 `web/vendor/` 上传。这些依赖不进入 Git，哈希和来源见 `web/vendor-manifest.json`。转换引擎约 31 MiB，仅首次转换时按需加载；网页、解析请求和运行文件仍会消耗站点流量。

部署配置见 [`deploy/x-download.service`](../deploy/x-download.service) 和 [`deploy/nginx.conf.example`](../deploy/nginx.conf.example)。使用独立系统用户 `xdownload`；源码放在 `/opt/x-download/current`，虚拟环境放在 `/opt/x-download/venv`，用该环境的 pip 安装 `requirements.txt`。FFmpeg 可使用已有系统版本，或单独放入 `/opt/x-download/bin/ffmpeg`。

Instagram 解析使用 yt-dlp 和 Instaloader（版本见 `requirements.txt`），只访问公开帖子，不加载用户账号会话。更新代码时也需同步安装依赖。匿名访问仍可能遇到登录要求或限流；不要依靠重复请求解除限制。Instagram 视频只返回含音轨的 MP4，不在服务器合并分离的音视频。

需要保留服务器处理时，将服务中的环境变量改为 `XDOWNLOAD_WEB_PROCESSING=server` 后重启下载器。此时媒体流量经过服务器，MP3 / GIF 需要本机 FFmpeg。浏览器模式不开放媒体转发接口；桌面版始终在本机处理。

```sh
/opt/x-download/venv/bin/python /opt/x-download/current/app.py \
  --web --no-browser --host 127.0.0.1 --port 18765 --production
```

`--production` 关闭本地诊断信息。systemd 示例限制 CPU 为一个核心、内存为 512 MB，适合小规模部署。将服务文件放入 `/etc/systemd/system/` 后启用 `x-download.service`。

在已有项目的服务器上，保留其他站点配置、依赖和服务，仅新增独立 Nginx 站点。后端端口绑定回环地址，经 HTTPS 反向代理访问。修改后先运行 `nginx -t`，通过后平滑重载 Nginx。

示例关闭代理缓冲和缓存、限制解析请求与下载并发，避免媒体缓冲到磁盘。CDN 也应关闭下载路由缓存。公网带宽额度应按实际服务器容量配置。

需要网页提供 Windows 下载时，将 EXE 放在源码目录的 `release/current/Dongdong.exe`；Linux 服务不需要安装桌面依赖。

## 免费 HTTPS 与自动续期

线上演示使用 Let's Encrypt 和 Certbot。`x.dd-oss.com` 的独立 Nginx 配置为 `/etc/nginx/sites-available/x-download`。

- 采用 `webroot` 验证，目录为 `/var/lib/x-download-acme`。
- HTTP 站点保留 `/.well-known/acme-challenge/`，其余请求跳转到 HTTPS。
- `certbot.timer` 定期检查，在到期前续期。
- `/etc/letsencrypt/renewal-hooks/deploy/x-download.sh` 在续期成功后检查 Nginx 配置并平滑加载证书。

维护时保留域名 A 记录、公网 80 / 443 端口、验证路径及计时器。无需在域名注册商购买 SSL。

```sh
systemctl list-timers certbot.timer
certbot renew --cert-name x.dd-oss.com --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

## 网络代理

Requests 会使用受支持的环境代理，也可通过启动参数或 `DONGDONG_PROXY` 指定：

```sh
python app.py --web --proxy http://127.0.0.1:7890
```

本项目不附带代理服务。

## Windows 打包

在 Windows x64 上准备 Python 虚拟环境和 FFmpeg：

使用 python.org 的标准 Python 发行版创建虚拟环境；不要把编辑器专用的 Python 运行时打入发布包。需要其他虚拟环境时，可通过 `build.ps1 -PythonPath <python.exe>` 指定。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\build.ps1 -FFmpegPath C:\path\to\ffmpeg.exe
```

默认产物为 `release/current/Dongdong.exe`。独立窗口依赖 WebView2；缺少运行时可安装微软官方 WebView2 Runtime，或使用附带的 `start-web.bat` 在浏览器中运行。单文件 EXE 启动时会解包运行时，首次打开可能需要几秒钟；这不是媒体缓存。当前构建未作代码签名。

## 桌面更新

仅在“关于”中点击“检查更新”时请求版本信息，不自动安装或强制更新。

`updates.json` 配置官网版本清单和 GitHub 备用来源。当前使用 `274335390/x-download` 的正式 Releases，标签为 `v1.0.0` 这样的三段版本号，发布附件需包含 `Dongdong.exe` 或 `Dongdong-Windows.zip`。没有 Release 时会明确提示，网络错误不会显示为“已是最新版”。

官网清单支持 `version` 与 HTTPS `url` 字段。更新检查不上传帖子链接或下载历史。

## 资源与数据

解析元数据在内存中约 30 分钟后过期。每个页面一次处理一个下载或转换任务；单次任务最多 256 MiB。关闭下载弹窗时会询问是否取消，确认后终止当前任务。浏览器 Blob 和 WebAssembly 会消耗用户内存，浏览器自身可能生成缓存或 `.crdownload`。服务器模式最多同时处理两个媒体任务，媒体、ZIP 和 FFmpeg 输出走流式管道，不主动生成媒体临时文件。Windows 直接写入用户选择的最终文件，失败时尝试清理本次未完成文件。

品牌图标位于 `web/brand.svg`、`web/brand.png` 和 `web/brand.ico`。重新分发前阅读 [第三方组件说明](../THIRD_PARTY.md)，媒体内容不受本项目 MIT 代码许可授权。
