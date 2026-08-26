# mhc-desktop 打包分发热知识

> 这份文档把 `mhc-desktop` 打包过程中踩过的坑、当时为什么这样决策、以及哪些地方**未来必须改/可能要改/只是凑合**全部固化下来。
> 不重复 README 里"怎么跑"的步骤；只讲"为什么这么跑"和"哪儿有雷"。

---

## 1. 整体架构决策

### 1.1 为什么后端自己服务 SPA？

**决策**：SPA 通过 `mhc_desktop_backend.app._mount_spa` 挂载到 FastAPI 同一个 origin，Electron `mainWindow.loadURL("http://127.0.0.1:<port>/")`。

**试过的替代方案**：

| 方案 | 失败原因 |
|---|---|
| `mainWindow.loadFile("dist/index.html")` + 同进程后端 | 渲染进程的 `/api/v1/...` 是相对路径，`file://` 下解析到系统根，404 |
| Electron 内嵌一个 Node http 服务器静态代理 | 双进程双端口，复杂且和 mh-local 现有"后端服务 SPA"的模式不一致 |
| **后端自己挂 static + SPA fallback** | **采用** — 借鉴 mh-local 的 `_mount_mh_local_static` |

**坑**：相对 URL `/api/v1/...` 在 `file://` 下不能工作；同一个 origin 是唯一干净的选择。

### 1.2 为什么用 PBS（无 venv）而不是 PyInstaller？

| 方案 | 字节 | 备注 |
|---|---|---|
| PyInstaller `--onefile` | 80–150MB 单 exe | 启动慢；需手动维护 excludes/hidden imports；data 文件要 `datas=` |
| PyInstaller `--onedir` | 类似，但文件夹 | 仍需排除规则 |
| **PBS + 依赖装进 PBS 自身 site-packages（无 venv）** | **67MB Python（含 deps）** | **采用** — 透明可调试、可搬移、和开发环境同构 |
| PBS + venv | 67MB + 100MB | ❌ 踩过坑：`pyvenv.cfg` 固化打包装机绝对路径，用户机器 exit 103（§5.3） |
| 系统 Python | 0 | 用户机器没装 Python |

**PBS 的额外好处**：python-build-standalone 的 tar 是一份完整的 CPython 发行版，无需 PATH 注册。**重要**：不要 `-m venv` 建 venv —— Windows 上 venv 不可搬移（launcher stub + `pyvenv.cfg home` 绝对路径），这是第一个真实发版事故（exit 103 / "No Python at"）。直接 `uv pip install --python python/python.exe` 把依赖装进 PBS 的 `Lib/site-packages`,启动时跑 `python/python.exe` 本身，`sys.prefix` 跟随 exe 位置，任意路径可跑。

### 1.3 为什么 `--dir`（不打包成单一 exe）？

打包 705MB（解压），压缩成 NSIS 后 **127MB**。如果用 `electron-builder --dir` 产物是 win-unpacked/，体积更大但启动更快、调试更直接。NSIS 走的是 LZMA2 压缩的 7z 自解压，启动慢几秒但分发友好。

两个产物都保留：`--dir` 给开发/调试，`--publish never` 给分发。

---

## 2. 中国大陆网络环境的固定雷区

### 2.1 Electron 二进制下载

GitHub 在国内抽风是常态。强制走镜像：

```bash
export ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
export ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/
```

变量名来自 `app-builder-lib/out/binDownload.js`：
```
process.env.npm_config_electron_builder_binaries_mirror
process.env.ELECTRON_BUILDER_BINARIES_MIRROR
```

二者都设上，前者是 npm 配置层、后者是 electron-builder 直读。

### 2.2 PyPI 国内镜像

PBS 的 Python 没问题，但依赖要装进 PBS 自身的 site-packages。`uv pip install --python python/python.exe --index-url https://mirrors.aliyun.com/pypi/simple/ ...` 每次重打 bundle 都要跑（§6.1）。aliyun 是综合可用性最好的；清华源偶尔挂。

`uv_build` 编译 `mhc-desktop-backend` 时也会去 PyPI 拉 transient deps，记得给 `uv` 也配镜像：

```bash
# ~/.config/uv/uv.toml 或项目根 pyproject.toml 的 [tool.uv.index]
[[tool.uv.index]]
url = "https://mirrors.aliyun.com/pypi/simple/"
default = true
```

### 2.3 `winCodeSign` 符号链接死结

**症状**：`winCodeSign-2.6.0.7z` 解压报错：
```
ERROR: Cannot create symbolic link : 客户端没有所需权限 :
  C:\Users\...\darwin\10.12\lib\libcrypto.dylib
```

**根因**：archive 里 `lib{crypto,ssl}.dylib` 是符号链接（21/18 字节），tar 协议把 symlink 表示成"内容是目标路径的 tiny 文件"。bundled `7za.exe` 试着**真创建符号链接**失败 —— Windows 没有 Developer Mode 或 admin 权限就调不到 `CreateSymbolicLink`。

**试过的修复**（按可行性排序）：

1. **HKCU 开 Developer Mode**：`reg add HKCU\...\AppModelUnlock /v AllowDevelopmentWithoutDevLicense /d 1 /t REG_DWORD /f`。但需要当前 cmd.exe 进程之后启动的才能继承 —— 已运行的进程不生效。
2. **覆盖 7za.js 走 .cmd shim 排除 darwin/linux**：写 `7za-wrapper.cmd` 只在解压时有效，但 Node 22+ 起 `execFile` 因为 CVE-2024-27980 拒绝 spawn `.cmd`/`bat` 没有 `shell:true` → `spawn EINVAL`。
3. **✅ 缓存预提取**（采用）：用 7za 的 `-xr!darwin -xr!linux -xr!appxAssets` 排除不需要的目录，把 `winCodeSign-2.6.0/` 整个预先放到 `%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\`。electron-builder 的 cache 检查通过 → 跳过重新下载/解压。

  注意：
  - 缓存目录名是版本化的（`winCodeSign-2.6.0`），electron-builder 升级会换名字。
  - Windows 构建只用 `rcedit-{x64,ia32}.exe`，darwin/ 和 linux/ 完全可以不要。
  - 解压后核对 `rcedit-x64.exe` 存在（1.3MB）才算成功 —— 之前 7za-wrapper 的失败版本看似 OK 但目录是空的，**一定要 verify**。

### 2.4 PBS（CPython 发行版）下载

直接 `curl https://github.com/astral-sh/python-build-standalone/releases/...`
在国内超时是常态。`scripts/build-bundled-python.{sh,ps1}` 现在按顺序试：

1. `https://registry.npmmirror.com/-/binary/python-build-standalone/{VER}/{TGZ}`
2. `https://github.com/...` （官方源）
3. `https://gh-proxy.com/https://github.com/...` （HTTP GitHub 代理）

如果都失败才会报错。国内基本第 1 条就返回 200，~30 MB、~10s。

### 2.5 `pyright` / `tsc` 不受影响

它们走 npm 的镜像，跟 Electron 二进制无关 —— `~/.npmrc` 里 `registry=https://registry.npmmirror.com` 已有。

---

## 3. electron-builder 配置里容易出错的地方

### 3.1 asar 入口路径必须对得上 package.json 的 `main`

**症状**：NSIS 阶段报错：
```
Application entry file "main.js" in "...app.asar" does not exist
```

**根因**：`files: ["dist/**/*"]` 会把 `dist/` 前缀**保留**进 asar，所以 asar 里有 `\dist\main.js`，但 `package.json`（在 asar 根）写 `"main": "main.js"` → 找不到。

**三个修法（任选）**：

1. **改 `outDir` 到项目根**（已采用）：
   ```json
   // tsconfig.json
   "outDir": "./"
   ```
   ```json
   // package.json
   "main": "main.js",
   "files": ["main.js", "preload.js", "package.json", ...]
   ```
   `tsc` 输出 `main.js` 到根。副作用是源码根污染了 build 产物，需要 `.gitignore` 加 `main.js` `preload.js`。

2. **`extraMetadata` 覆盖 main 字段 + 调整 files 让 main.js 到 asar 根** —— 更复杂不推荐。

3. **走 `dist/` 但 asar 里也写 `dist/main.js`** —— 让 outer package.json 的 main 字段写成 `dist/main.js`，然后 `extraMetadata.main: "dist/main.js"` 同步进 asar。已试过，可行但更绕。

### 3.2 `[tool.setuptools.package-data]` 必须声明 static/

**症状**：安装包构建后 SPA 404，因为 `mhc_desktop_backend/static/` 没被打包。

**根因**：`uv_build` 默认**只打包 `.py`**，数据文件要显式声明。

```toml
[tool.setuptools.package-data]
mhc_desktop_backend = ["static/**/*"]
```

**注意**：build-spa 必须先把 SPA 复制进 `src/mhc_desktop_backend/static/`，否则 wheel 仍然是空的。这个顺序要在文档里写清楚，否则新人会先装 wheel 再问"为啥没 SPA"。

### 3.3 main.ts 不要硬编码端口

**症状**：开发机上 8765 被多个 python -m_huv 僵尸进程占着，新启动的 backend 立刻 `bind on 8765 failed` 退出。

**修法**：`net.createServer` 探测 `8765..8770`，第一个能 bind+release 的端口就是 backend 的 MHC_PORT。

```typescript
async function pickPort(): Promise<number> {
  for (const port of SPA_PORT_SCAN) {
    if (await canBind(port)) return port
  }
  return BACKEND_PORT
}
```

`canBind` 必须在 spawn 之前完成 —— 否则 backend 启动后才发现端口被占就直接死了，连重试机会都没有。

### 3.4 Electron 主进程要 `MHC_RELOAD=0`

**症状**：bundled 启动后数秒自己重启一次（reloader 监听到 `site-packages` 变化触发 reload → loop）。

**修法**：spawn 时显式 `env.MHC_RELOAD = "0"`。开发环境不设（保留 uvicorn 的 auto-reload）。

### 3.5 asar `files` 不收 `..` 越界路径 —— 跨包目录的产物必须走 `extraResources`

**症状**（2026-08-25 用户机白屏）：
- Electron 窗口纯白屏、没有 splash、按钮全无
- 后端 spawn + `/ready` 200 都正常（独立看后端"活"）
- 日志连报：
  ```
  failed to stage injected SPA index: Error: ENOENT: no such file or directory,
    open 'D:\Program Files\mhc-desktop\resources\mhc-desktop-frontend\dist\index.html'
  loading SPA at file://D:/Program Files/mhc-desktop/resources/mhc-desktop-frontend/dist/index.html
  SPA failed to load (-6) ERR_FILE_NOT_FOUND
  ```

**根因**：`mhc-desktop-app/package.json` 的 `files` 写了 `../mhc-desktop-frontend/dist/**/*`，**electron-builder 会静默丢弃任何跨越 `..` 逃出 package 根的 glob**——不报错、warning 也没有。asar 里没有 SPA；main.ts 用 `path.resolve(__dirname, "..", "mhc-desktop-frontend", "dist")` 计算出的目标路径在用户机 `resources/` 下从未被创建 → ENOENT。

验证方法：
```bash
npx --prefix packages/mhc-desktop-app asar list \
  packages/mhc-desktop-app/dist/win-unpacked/resources/app.asar | grep -i frontend
# 应该返回 0 行 —— SPA 不在 asar 里
```

**修法**：跨包目录的资源必须走 `extraResources`，跟 backend 同模式。把 SPA 从 `files` 移到 `extraResources`：

```json
"files": ["main.js", "main.js.map", "preload.js", "preload.js.map", "package.json"],
"extraResources": [
  {
    "from": "../mhc-desktop-frontend/dist",
    "to": "spa/dist",
    "filter": ["**/*"]
  },
  {
    "from": "build-resources/backend",
    "to": "backend",
    "filter": ["**/*"]
  }
]
```

main.ts 同步改成 packaged 走 `process.resourcesPath/spa/dist`，与 `bundledBackendDir()` 对称：

```typescript
function spaDistDir(): string {
  if (!app.isPackaged) {
    return path.resolve(__dirname, "..", "mhc-desktop-frontend", "dist")
  }
  const rp = (process as unknown as { resourcesPath?: string }).resourcesPath
  if (!rp) return path.resolve(__dirname, "..", "mhc-desktop-frontend", "dist")
  return path.join(rp, "spa", "dist")
}
```

**额外后果**：install 后 `resources/spa/dist/` 会和 `resources/backend/python/Lib/site-packages/mhc_desktop_backend/static/`（前者给 `file://` 加载用，后者给后端 `/` 同源服务用）两份相同的 SPA dist。加起来比之前大约 +16MB 压缩后体积，可接受。**不**要去掉后端那份：第 5 节 SPA fallback 仍依赖 `static/`。

**为什么这个 bug 早期没被发现：asar `..` 静默丢弃不是 0/1 行为——它只是"扔掉"，连 warning 都不会有**。只在没有走 SPA fallback（用户双击独立 exe）这种"必须 main.ts 自己找 SPA"的场景下才暴露。dev mode 用 vite，不走 asar，永远不触发。

**调试贴心提示**：如果用户机器白屏但后端 `/ready` 200，先看 `mhc-desktop.log` 里的 `loading SPA at file://...` 后面那个路径——再 `ls` 一遍用户机器的 `resources/` 看看那个路径是否存在。99% 是这个坑。

### 3.6 打包阶段把 `content-packs/` 一起 ship + 后端 lifespan 启动时 materialize

**背景**（2026-08）：刚反了的决策。`content-packs/README.md` 过去明确说"The installer itself stays empty"——原因记录在 §5.3。但 mhc-desktop 这种**面向特定客户**的产品，每个客户想要自己的默认 skill 集，“另行 zip 导入”设计反而成了负担。

**最终架构**：`packages/mhc-desktop-app/content-packs/{skills,tools,mcp}/` 下的一切 ship 进安装包（`extraResources` → `resources/content-packs/`）；后端 `create_app()` 的 lifespan 启动调 `materialize_bundled()`，扫那个目录、把每个 unit 装进 `~/.mhc-desktop/{skills,tools,mcp}/<slug>/`。

`packages/mhc-desktop-app/package.json` 配置：

```json
"extraResources": [
  {
    "from": "../mhc-desktop-frontend/dist",
    "to": "spa/dist",
    "filter": ["**/*"]
  },
  {
    "from": "../mhc-desktop-app/content-packs",
    "to": "content-packs",
    "filter": ["**/*", "!**/__pycache__/**", "!**/*.pyc"]
  },
  {
    "from": "build-resources/backend",
    "to": "backend",
    "filter": ["**/*"]
  }
]
```

main.ts 传递 `MHC_RESOURCES_PATH` 给后端（ `process.resourcesPath`）。后端 `app.py` lifespan 启动读这个 env var、作为 content root。

**三个不变量（被 `tests/test_content_packs.py` 锁住）**：

1. **幂等启动**：同一个 installer 启两次不重复装 unit。第一次 materialize 是安装，第二次是 `summary.skipped[]`。验证在 `test_materialize_bundled_is_idempotent`。
2. **用户定制不被覆盖**：bundled unit 在 user data 目录里被用户改过 body 后、装机关一启，不会被 bundled 副本刷回去。`overwrite=False` 是默认；手动重启 materialization 需要用户先删 `~/.mhc-desktop/skills/<slug>/`。验证在 `test_materialize_bundled_preserves_user_edits`。
3. **坏的 unit 不拖累全 batch**：某个 `tool.py` 有语法错误只跳到 `summary.errors[]`，其他 unit 照样装。验证在 `test_bulk_install_tools_broken_tool_records_error`。

**可幂等 vs. 热更新**：因为默认不 overwrite，**bundled 内容升级不会自动推到已装的用户机器上**。这是故意设计的（见 `content-packs/README.md` "When the bundled unit already exists..."）——避免“下次启动后用户改过的 body 没了”。推升级需要用户在管理页手动重装包（`import_pack.zip` 入口依然存在，覆盖 `import-bulk` 路由的还是同一套代码）。

**Dev vs packaged**：

- dev 模式（`app.isPackaged=False`）：lifespan 里的 materialize 调用读不到 `MHC_RESOURCES_PATH` env var → 什么也不做。你手动改 `content-packs/skills/<slug>/SKILL.md` 、从管理页重装包、能看到效果。
- packaged 模式：lifespan 启动读 `MHC_RESOURCES_PATH/content-packs` 、`summary` 记到日志（`content_packs.skills installed=… skipped=… errors=…`）。想知道有没有装成功看 `mhc-desktop.log`。

**调试贴心提示**：

- "用户机器上 bundled skill 丢了"：先看 `~/.mhc-desktop/skills/<slug>/` 是否还在，被用户手动删过、或者升级过安装包但有同 slug 的旧版本（bundled 默认不 overwrite，但手动 `import-bulk` 走 `store.create` 会报 "already exists"）。看 log：`content_packs.skills skipped=1` 说明后端检测到了同名 unit、跳过了。
- "装机后 bundled tool 加载不了 / 报 callable not loaded"：检查 `~/.mhc-desktop/tools/<slug>/tool.py` 是否存在。后端会顺手在 materialize 阶段把 bundled `tool.py` 复制到 store 目录下，但如果中途被 AV 扫描、或者用户手动删过，下次启会重新掊一份。
- "想临时要 overwrite 跳过用户定制"：不能从 installer 里跳（lifespan 硬写 `overwrite=False`）。要推升级就在管理页让用户手工重装一次 zip，或者临时改代码、升个版本。

---

## 4. Electron 主进程的细节坑

### 4.1 `process.resourcesPath` 在 dev mode 下是 undefined + env var 不能跨生命周期复用

`bundledBackendDir()` 用 `process.resourcesPath` 判断是否在打包环境。dev mode 下 `process.resourcesPath` 不存在 → 回落路径：

- 用户设了 `MHC_BUNDLED_BACKEND` → 用它（dev 调试用）
- 都没 → uv 路径

dev 调试时 `MHC_BUNDLED_BACKEND=/path/to/build-resources/backend` 可以强制走 bundled 路径、不启 vite、不依赖 uv。

**重要**：这个 env var **必须只存在于 dev**。曾经犯过的一个 bug：用户报告 packaged app 报

```
No Python at '"C:\\Users\\Administrator\\Documents\\repo\\mh-incubator\\packages\\mhc-desktop-app\\build-resources\\backend\\python\\python.exe'
```

同一条 spawn 调用，stdout 报 `[backend] spawning bundled: C:\\Users\\l00617843\\AppData\\Local\\Programs\\mhc-desktop\\resources\\backend\\venv\\Scripts\\python.exe` （**对**的路径）但 stderr 报找不到的是**开发者机器**上的路径。原因：用户 shell 里残留着我调试时设的 `MHC_BUNDLED_BACKEND`，值是我开发机的 build-resources。原代码无条件 env 优先于 `process.resourcesPath` → packaged app 拒绝用 asar 里的 backend。

**修法**：用 `app.isPackaged` 闸门：

```typescript
function bundledBackendDir(): string | null {
  const rp = (process as unknown as { resourcesPath?: string }).resourcesPath
  if (!app.isPackaged && process.env.MHC_BUNDLED_BACKEND) {
    return process.env.MHC_BUNDLED_BACKEND
  }
  if (!rp) return null
  return path.join(rp, "backend")
}
```

**调试贴心提示**：在诊断 packaged crash 时，如果看到 `[backend] spawning bundled:` 后面是一个你机器上没有的路径，基本就是这个 env var 被泄到这个用户环境了。同样 Windows 上 `setx` 设过的环境变量会**重启**才消失。提示用户检查环境变量或者写一个一键 unset 小脚本。

### 4.2 Electron `--dir` 产物会在第一次跑完后还活着

`Get-Process mhc-desktop -ErrorAction SilentlyContinue | Stop-Process -Force` 是反复调试时的标配。PowerShell 找不到进程时打印中文乱码是正常的，不影响退出码。

### 4.3 `--mhc-dev-url` flag

只在 argv 里加 flag 时才认，**而且要带值**：`electron . --mhc-dev-url http://127.0.0.1:5180`。`--mhc-dev-url` 单独写（不跟值）会被当作另一个 flag，DEV_URL 仍是默认值 → vite 启动顺序问题。

### 4.4 Silent launch failure 不应只依赖 `app.quit()`

用户双击 exe "什么都不发生" 是个真实问题：原先 `before-quit` 超时后只是 `app.quit()`，连个对话框都没有。

修法：
- 重写 `console.log` / `console.error` 同时写 `%APPDATA%/mhc-desktop/mhc-desktop.log`，从原始问题发生开始就能定位。
- 后端 `child.on('error')`（`spawn` 失败）必须有 handler。原代码只听了 `exit`，spawn 错（如 venv 路径不存在）静默丢。
- `before-quit` 超时后用 `dialog.showMessageBox` 弹 "Open log folder" / "Quit"，点第一个会调 `shell.openPath` 打开日志所在目录。

要测 graceful shutdown 用 `CloseMainWindow()`，**不要**用 `Stop-Process -Force`。后者是 `TerminateProcess`，根本没机会触发 `before-quit` 事件，看起来"一切都死了" 但其实是 `TerminateProcess` 顺手杀了进程树，验证不到我们的等待逻辑。

### 4.5 首启动慢启动不能误判为启动失败

**症状**：用户装到机器上以后双击 exe，等了 30 秒弹“后端启动失败”对话框，但实际后端再过几十秒会起起来。问题不是后端起不来，是**冷启动真的慢**。

**根根因**：出厂 venv + PBS Python 打包后 ~7000 个文件在 `%LOCALAPPDATA%` 下。Win11 上首次运行时：
- Windows Defender / 第三方 AV 扫描每个 DLL 和 .pyc，30–90 s 很正常
- 机械硬盘随机 I/O 读 7000 个文件
- uvicorn factory import 链本身 ~5 s

原来代码设了 `READY_TIMEOUT_MS = 30_000`，只要没到 30 秒就提示弹弹失败 → 报错后调 `app.quit()`。但后端“就在要起起起”状态下被我们杀了。

**修法**（三处同步改）：
1. `READY_TIMEOUT_MS` 提到 90 s。超时后不 quit，只弹一个警告对话框告诉用户是 AV 扫描在跑，后台还在重试。
2. 后台 `watchBackendReady()` 另起一个 promise，最多再等 120 s。后端一旦 /ready 返回 200，调用 `mainWindow.webContents.reloadIgnoringCache()` 让 SPA 重新拉数据恢复。
3. SPA 顶上加一个 `.backend-startup` 黄条，从启动起每 1.5 s 拉 `/api/v1/health`，后端就绪后消失。告诉用户“后端正在启动…最多需要 2 分钟”。

**调试线索**：用户日志中的时间间隔是诊断关键。如果“Starting mhc-desktop backend”和“bundled tools available”之间隔了 30+ s，几乎肯定是 AV 扫描。如果隔了 3 s 以内但还是超时，检查后端是否因路径问题 exit 103（详见 §5.3 的 venv 固化路径），以及 main.ts 的 spawn 路径是否与打包结构一致。

---

## 5. SPA 服务的 FastAPI middleware

### 5.1 fallback 顺序

```python
@app.middleware("http")
async def _spa_fallback(request, call_next):
    response = await call_next(request)
    if (
        response.status_code == 404
        and request.method == "GET"
        and not request.url.path.startswith("/api")
        and not request.url.path.startswith("/docs")
        ... # mounted static
    ):
        if index.is_file():
            return FileResponse(str(index))
    return response
```

**坑**：不要对 `/api/*` 走 fallback（否则 API 的 404 被 SPA 吃掉），也不要对已 mount 的 `/assets` `/fonts` 走 fallback。mh-local 在这里有个等价的实现可以参考，但 mh-local 还 mount 了 `/component` —— 我们没用到。

### 5.2 mounted static 的目录检查要 lazy

```python
for sub in ("assets", "fonts"):
    p = static_dir / sub
    if p.is_dir():
        app.mount(f"/{sub}", StaticFiles(directory=str(p)), ...)
```

开发期 `static/` 不存在时（还没跑 build-spa），中间件要**静默跳过**而不是崩溃。这是 `_mount_spa` 顶层 `if not static_dir.is_dir(): return` 的用意。

### 5.3 pyvenv.cfg 固化路径导致 "No Python at..." exit 103 —— 已根治

**症状**：开发机运行良好；安装到用户机上，`venv\Scripts\python.exe` 一启动就报错

```
No Python at '"C:\Users\Developer\Documents\repo\...\build-resources\backend\python\python.exe'
```

stdout 看起来像是成功启了 venv python，stderr 直接报找不到 base interpreter，`exit code=103` 退出。这是"装到别人机器上就崩"的头号黑洞，用户机器上第一版报错就是它。

**根因**：`python -m venv` / `uv venv` 生成的 `pyvenv.cfg` 里 `home`/`executable` 字段写的是**创建时的绝对路径**（打包装机的路径）。安装到用户机器后这些路径不存在，venv 的 launcher stub（`Scripts\python.exe`）按 `home` 找 base interpreter，找不到就打印 `No Python at` 并 exit 103。

**为什么不能简单修 pyvenv.cfg**（踩过的坑）：
- 改成相对路径 `home = ..\python` — CPython 3.12 不认，报 `No Python at "..\python\python.exe"`
- 删掉 `home`/`executable` — `sys.base_prefix` 仍指向旧绝对路径
- venv 在 Windows 上本质上**不可搬移**（launcher 必须解析出 base interpreter 的绝对路径）

**最终修复**：不要 venv 这层。`build-bundled-python.ps1` 改为把依赖直接装进 PBS base 解释器自己的 `Lib\site-packages\`，运行时直接跑 `python\python.exe`：

```powershell
uv pip install --python "$OUT/python/python.exe" --index-url https://mirrors.aliyun.com/pypi/simple/ fastapi 'uvicorn[standard]' openai anthropic
uv pip install --python "$OUT/python/python.exe" --no-deps <workspace 包目录>
```

main.ts 同步改成 spawn `resources/backend/python/python.exe`（win32）。没有 venv、没有 pyvenv.cfg、`sys.prefix` 跟随 exe 位置 → **可搬移**。

**回归验证（每次发版必做）**：

```bash
# 1. 打包后把 resources/backend 拷到任意其它路径（模拟用户机器）
cp -r dist/win-unpacked/resources/backend /tmp/reloc-test-backend
# 2. 从拷出来的位置直接启动后端
cd /tmp/reloc-test-backend && MHC_PORT=8931 ./python/python.exe -m mhc_desktop_backend
# 3. /ready 200 即通过；日志里不应有任何 "No Python at"
```

---

## 6. 构建脚本的几个坑

### 6.1 顺序很重要

```
1. build-spa              → 把 dist 复制到 backend/src/.../static/
2. build-bundled-python   → uv pip install 重装 workspace wheel，把新 static/ 连同
                           后端代码一起装进 python/Lib/site-packages
3. electron-builder       → 读 package.json 的 extraResources 配置：
                           - resources/backend/  ← python/ 整个 PBS
                           - resources/spa/dist/  ← mhc-desktop-frontend/dist 的副本
                           （SPA 不能进 asar：参看 §3.5）
                           asar 里只装 main.js / preload.js / package.json，
                           NSIS 把整个产物压缩成安装包
```

如果 step 1 漏了，wheel 里没 SPA；**step 2 漏了是真实事故**——2026-08 有一次只跑了 1+3，安装包里还是旧前端（无限刷新 bug 的旧 main.js），用户机器表现为"页面反复刷新"。每次改前端都必须按 1→2→3 全跑，任何一步跳过都会发一个坏包。

### 6.2 不要把 .pdb 一起打包

PBS 的 `python.pdb`/`python3.pdb`/`pythonw.pdb` 加起来 ~60MB，运行时毫无用处。`build-bundled-python.{ps1,sh}` 里有：
```bash
find "$OUT/python" -name "*.pdb" -size +1k -delete
```
保留小 .pdb（kernel32 调试用的）不影响。

### 6.3 不要清理 python/Lib/site-packages

site-packages 现在直接住在 PBS 的 `python/Lib/site-packages`（无 venv）。听起来反直觉：里面有些 `.tests` 目录几十 KB（certifi、colorama 等）可清，但 PyInstaller 场景下的"瘦身"做法**不适用** —— 我们直接 ship 整个 site-packages。清过头会导致 import 失败。

**保留**：所有 `*.dist-info/`、`__pycache__/`（首次启动会重建）、`.libs/` DLL。

---

## 7. 验证清单

每次改打包配置后跑一遍：

- [ ] **NSIS 产出**：`dist/mhc-desktop Setup *.exe` 存在且 > 50MB
- [ ] **解压安装包**：`7za x "dist/mhc-desktop Setup *.exe" -o/tmp/test` 不报错
- [ ] **SPA 已 staged**：`win-unpacked/resources/spa/dist/index.html` 存在且 ≥ 1KB（不是空文件）；`assets/` `fonts/` `brand.svg` 也在（参看 §3.5）
- [ ] **SPA 不在 asar 里**：`npx asar list win-unpacked/resources/app.asar | grep -i frontend` 必须返回 0 行
- [ ] **bundled 后端启动**：`/path/to/test/resources/backend/python/python.exe -m mhc_desktop_backend` → `/ready` 返回 200
- [ ] **bundled content-packs 已 staged**：`win-unpacked/resources/content-packs/{skills,tools,mcp}/` 存在且非空（参看 §3.6）；`ls win-unpacked/resources/content-packs/skills/create-skill/SKILL.md` 返回存在
- [ ] **bundled content 不含 __pycache__**：`find win-unpacked/resources/content-packs -name __pycache__` 必须返回 0 行（extraResources filter 有 `!**/__pycache__/**` 排除规则）
- [ ] **SPA 入口**：`/` 返回 index.html 200
- [ ] **静态资源**：`/fonts/HarmonyOS_Sans-Regular.ttf` 200
- [ ] **API**：`/api/v1/health`、`/api/v1/providers` 200
- [ ] **打包 exe 启动**：双击或 `Start-Process mhc-desktop.exe` → 弹出窗口
- [ ] **packaged 不被环境变量污染**：设 `MHC_BUNDLED_BACKEND=...不存在路径...` 后再启动 packaged exe，后端仍能从 `resources/backend/...` 起来，日志里的 spawn 路径是 `process.resourcesPath` 而不是 env var
- [ ] **graceful 退出不留孤儿**：`CloseMainWindow()` 后等 6s，`Get-Process mhc-desktop` 和 `Get-WmiObject Win32_Process -Filter "Name='python.exe'" | Where CommandLine -like '*mhc-desktop-app*'` 都为 0
- [ ] **slow-start 路径不误杀**：`watchBackendReady()` 能看到带人工延迟（中间加 60 s sleep）的 backend 起来并 reload 渲染进程；日志显示"backend became ready in background"
- [ ] **可搬移性**：把 `resources/backend` 拷到任意其它路径直接跑 `python/python.exe -m mhc_desktop_backend`，`/ready` 200、日志无 "No Python at"（§5.3）
- [ ] **SPA 与 bundle 同步**：`build-spa` 必须先于 `build-bundled-python` 执行，否则打包进 bundle 的仍是旧前端（重打 bundle 才会把新 `static/` 装进 site-packages）
- [ ] **NSIS 卸载成功**：安装后立即退出应用 → 控制面板卸载 → 不出现 "app is running" 错误
- [ ] **窗口能加载 SPA**：观察 Electron 子进程的 stdout 应该有 `GET /` `GET /assets/...`

已完整体检的补丁（2026-08 实战）：
- [ ] **首启动 30–90s 慢不等同于失败**：后端有 `Starting ...` 日志但迟迟不 `ready` 是 AV 扫描的常态，等它起来即可（§4.5）。若 `Starting` 后几秒内就 exit 103，才是路径问题（§5.3）
- [ ] **无无限刷新**：等后端就绪后让应用跑 30s，日志里 `GET /` 只有 1 次（`waitForBackend` / `window.location.reload()` 整段已删，`<base href>` 下相对 `fetch` 永远命中 `file://` 而 throw，必 reload 的死循环已无源头）
- [ ] **日志时区统一上海**：`mhc-desktop.log` 里 Electron 行是 `+08:00`、后端/uvicorn 行也是 +08:00，无 UTC `Z` 残留

任意一项不过就是回归 —— 别急着发版。

---

## 8. 已知未做的（未来要做）

按"投入产出比"排序：

1. **代码签名**：当前 unsigned，Windows 会弹 SmartScreen 警告。要 `CSC_LINK` + `CSC_KEY_PASSWORD`，或者用 Azure Trusted Signing。10 分钟配置 + 每年证书钱。
2. **macOS .dmg + notarization**：需要 Apple Developer ID + notarytool。M-series Mac 上跑 PBS 变体（`aarch64-apple-darwin`）。
3. **Linux AppImage**：PBS 变体 `x86_64-unknown-linux-gnu`。Linux 桌面用户少，可以晚点。
4. **自动更新**：`electron-updater` 集成。一行配置 + 一个 GitHub releases 流水线。
5. **错误上报**：生产环境的 backend 崩溃日志目前写 `%LOCALAPPDATA%/mhc-desktop/logs`，没主动上报。要不要 Sentry 看你。
6. **精简 backend deps**：`anthropic` 包 15MB —— 如果只支持 OpenAI 兼容厂商可以不装。当前双支持没意义但也不痛。
7. **cygpath / POSIX launcher**：Linux/macOS 下 PBS base 里是 `python/bin/python3` 不是 `Scripts/python.exe`。main.ts 已按平台区分但没真测过，且 macOS/Linux 的 PBS 变体下载没验证过。
8. **NSIS 自定义 UI**：当前是默认 blue 主题，nsi script 没动过。可以加 banner、安装目录选择等。

---

## 9. 快速调试 cheat sheet

```bash
# 看 electron-builder 实际下载了什么
ls /c/Users/Administrator/AppData/Local/electron-builder/Cache/

# 看 packaged exe 的 stdio
powershell -Command "Start-Process -FilePath '.\dist\win-unpacked\mhc-desktop.exe' -RedirectStandardOutput out.log -RedirectStandardError err.log -PassThru"

# 杀掉所有 mhc-desktop 进程
powershell -Command "Get-Process mhc-desktop -ErrorAction SilentlyContinue | Stop-Process -Force"

# 直接调 packaged 的 backend（不经过 Electron）
./dist/win-unpacked/resources/backend/python/python.exe -m mhc_desktop_backend

# 看 installer 内部结构
./node_modules/7zip-bin/win/x64/7za.exe l "dist/mhc-desktop Setup 0.1.0.exe"

# 看 app.asar 内部结构
node -e 'const asar=require("@electron/asar"); const fs=require("fs"); fs.writeFileSync("/tmp/x.json", asar.extractFile("dist/win-unpacked/resources/app.asar", "package.json"));'
cat /tmp/x.json

# 用户机 packaged 报 "No Python at ..." 但 spawn 路径是对的：检查环境变量
powershell -Command "[Environment]::GetEnvironmentVariable('MHC_BUNDLED_BACKEND','User')"
powershell -Command "[Environment]::GetEnvironmentVariable('MHC_BUNDLED_BACKEND','Process')"
# 清掉
powershell -Command "[Environment]::SetEnvironmentVariable('MHC_BUNDLED_BACKEND', \$null, 'User')"

# 验证 packaged 忽略 env var（模拟用户场景）
\$env:MHC_BUNDLED_BACKEND = 'C:\nonsense\path'; .\dist\win-unpacked\mhc-desktop.exe
# 看 mhc-desktop.log：spawning bundled 后面应该是 resources/backend/... 而不是 C:\nonsense\path...
```

---

## 10. 这份文档的保质期

- electron-builder ≥ 26 可能改 binDownload.js 接口 → 检查 `ELECTRON_BUILDER_BINARIES_MIRROR` 是否还生效
- Electron 40+ 可能改 sandbox 默认值 → 检查 main.ts 的 `webPreferences`
- PBS 升级时 `static/` 目录默认结构变了 → 核对 `python/python.exe` 路径不变
- Windows 12 可能放宽 Developer Mode 默认 → winCodeSign 的符号链接问题可能自动消失

任一项变化后回头校对本文档第 2、3 节。

---

## 跨文档索引

- [`BUILTIN-CONTENT.md`](BUILTIN-CONTENT.md) — 如何往 `content-packs/`
  加新 skill / tool / MCP：文件 schema、dev 迭代、重打、ship、
  user upgrade 语义、troubleshooting。这一篇是本节（§3.6）内容的
  作者向展开，骨架在本文里、动手步骤在那边。

---

## 11. 实战复盘：从"装不上就跑不了"到用户机器可用（2026-08 连续四个发包的教训）

真实用户机器上依次暴露了 4 个问题，逐个排掉的顺序就是"打包正确经验"：

| # | 现象（用户机器日志） | 根因 | 修复 | commit |
|---|---|---|---|---|
| 1 | `No Python at '"C:\Users\开发机\...'` exit 103 | venv 的 `pyvenv.cfg` 固化打包装机绝对路径，Windows venv 不可搬移 | 删掉 venv 层，依赖直接装进 PBS 自身 site-packages，跑 `python/python.exe` | 0473a06 |
| 2 | 后端起来正常但 Electron "30s 超时"弹错 | `READY_TIMEOUT_MS=30s` 对首启动（AV 扫描 30–90s）太短，超时后还调用 `app.quit()` 把即将就绪的后端杀了 | 超时 90s + 后台 `watchBackendReady()` 再等 120s + 慢启动黄条提示，不误杀 | 4cde701 |
| 3 | 页面能出来但**无限刷新**，看起来"找不到后端" | `waitForBackend` 无条件在 health OK 后 reload → mount→OK→reload 死循环。后端其实活着 | 只在"挂载时后端 down、之后才 up"时 reload 一次 | 79f04b6 |
| 3b | 用过程中**3 分钟后突然白屏**：日志 `SPA failed to load (-6) .../resources/spa/dist/#/settings` | `sawFailure` 标志依赖相对 URL `/api/v1/health`，但注入的 `<base href>` 把 fetch 解析成 `file://.../resources/spa/dist/api/v1/health` → 永远 throw → 180s 后无条件 reload；reload 时 `os.tmpdir()` 里的注入 HTML 已被 `did-finish-load` 后的 `unlink` 删除（且 base 解析下 Chromium 报的是 install 路径 URL） | 删掉整个 `waitForBackend` IIFE；后端握手完全交给 App.vue 的 splash + `${__MHC_BACKEND_URL}/api/v1/health` 轮询，stores 自己按需重试 | (本轮) |
| 4 | 日志时间对不上本地 | 后端用机器本地时区、Electron 用 UTC `Z`，混在一个文件里 | 统一固定 Asia/Shanghai（无 DST，纯 +8h 算术偏移，零新依赖） | 2116c68 |
| 5 | 装到用户机后**窗口白屏**，后端 `/ready` 200 但 SPA 找不到 `resources/mhc-desktop-frontend/dist/index.html` | asar 的 `files` glob 不收 `..` 越界路径，electron-builder 静默丢弃；SPA 从未进安装包 | 把 SPA 从 `files` 移到 `extraResources`（与 backend 同模式，`to: spa/dist`），main.ts `spaDistDir()` 加 `app.isPackaged` 分支走 `process.resourcesPath/spa/dist`（§3.5） | 4b1b518 |
| 6 | “内容打包后怎么自动出现在应用里”是产品需求不是技术限制 | “installer ships empty”是为了“避免每个 release 携带客户不想要的内容”——但在面向特定客户的产品里，这反而是负担；客户花钱买的应用里默认是空的，遮了产品价值 | 把 `content-packs/` 加 `extraResources` 进安装包；后端 lifespan 启动调 `materialize_bundled()` 装进 user data；幂等 + 不 overwrite（§3.6） | (未提交) |

**复盘要点**：
1. **用户机器上的"启动失败"先别信对话框，先看日志时间线**。`Starting` 和 `ready` 之间隔 30s+ = AV 扫描（正常，等）；几秒内 exit 103 = 路径问题（真挂）。
2. **Electron 的 `app.quit()` 在慢启动场景下是破坏性的**——超时不代表后端死了，杀了它才是真失败。超时后保持窗口、后台续等。
3. **前端"恢复"逻辑最危险的是副作用**：reload 必须只在状态真的发生 down→up 迁移时触发，否则健康状态也触发 reload = 死循环，看起来比不修还糟。
4. **打包顺序是硬约束**：build-spa(前端) → build-bundled-python(重装 wheel 带 static) → electron-builder。跳过第 2 步 = 发旧前端（事故 3 的放大器）。
5. **日志是唯一的调试通道**，时区不一致导致无法对照时间线，等于自断双目。统一成一个时区（上海）是硬要求。
6. **venv 不可搬移是 Windows 平台级事实**，不是配置问题。凡是要"拷到别的机器跑"的 Python 环境，一律不用 venv。
7. **electron-builder 的 asar `files` glob 对 `..` 越界是静默吞，不是报错**——任何“理应”在安装包里的文件，如果用 `..` 跨出 package 根，要么改用 `extraResources`，要么把文件搬进 package 根再 glob。写完配置后**必须** `asar list` 一遍确认（§3.5）。
8. **“在装包阶段 ship 内容”需求，产品侧认为是理所当然、技术侧别怕 override 需求先推设计**。如果我们初始架构是“installer ships empty”，面对“客户想要预置内容”的需求、正确选择是改架构，不是写个 "build-time import-zip at install" 这种 "半实现"。装包阶段能力上限是 extraResources / NSIS custom action / winget dependency；直接用 extraResources + 后端启动 materialize是最贴仓（§3.6）。
