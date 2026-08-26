# mhc-desktop 自动更新机制

> 这份文档把"丝滑升级"拆成三档、按部件生命周期分别走不同的更新通道。
> 不重复 README/PACKAGING 里已有的发布步骤；只讲"为什么这么设计"和"哪儿有雷"。

---

## 1. 目标 & 非目标

### 1.1 目标

- **用户感知不到**：日常 SPA / 内容补丁在下一次启动时无缝切换，不弹安装向导、不弹 SmartScreen。
- **重大升级也只一次跳转**：Electron 壳 + Python runtime 大版本升级走 NSIS 完整包，但只有跨大版本（半年/年级别）才发生一次。
- **永远不回退到更差的版本**：新版启动失败能在 60 s 内自动回滚到上次好的版本，且不丢失用户数据。
- **国内网络可用**：不依赖 GitHub 直连；Tier 2/3 不依赖代码签名（代码签名只在 Tier 1 + 跨大版本才需要）。
- **自托管友好**：manifest URL 可指向任意 HTTPS 端点（GH releases / 自建 CDN / 内部对象存储），不绑死 GitHub。

### 1.2 非目标

- **差分更新（bsdiff）**：127 MB 全量对增量级工件来说体积还可控，差分链路复杂度不划算。等 Tier 2 真正成为流量大头再考虑。
- **强制 / 静默升级**：所有更新都需要用户在托盘点头（除了安全补丁级别，但当前不做）。
- **dev 模式更新**：dev 走 vite + uv，绕过整个机制。
- **macOS / Linux**：本设计以 Windows 为目标平台写细节；macOS 由 `electron-updater` 的 Squirrel.Mac 兜底，Linux AppImage 后续再做。

---

## 2. 三档更新通道

| 档 | 更新什么 | 通道 | 触发时机 | 是否需要签名 | 重启窗口 |
| --- | --- | --- | --- | --- | --- |
| **Tier 1** | Electron 壳 + Python runtime 大版本 | `electron-updater` 拉 NSIS 完整包 + 重装 | 跨 major（如 0.x → 1.x） | **是** | 一次性 NSIS 弹窗 |
| **Tier 2** | SPA `dist/` + bundled `content-packs/` | 后台下载到 `userData/staged-update/`，下次启动原子替换 `extraResources/` | SPA / 内容有改动 | 否（HTTPS + SHA256 已够） | 用户下次正常退出/启动 |
| **Tier 3** | Bundled Python backend wheel / PBS | 杀 child → 替换 `resources/backend/` → 重 spawn | 后端代码有改动 | 否 | **session 内可不退**（杀子进程替换再启） |

**为什么分档而不是一锅端**：

1. **部件生命周期不同**。SPA 改一行 CSS、bundled skill 加一个 `SKILL.md`、Python 解释器升级 —— 这三件事频率差两个数量级，强行打包进一个 NSIS 包会让用户每次都下 127 MB。
2. **签名成本和灵活性互斥**。Tier 2/3 不签名 = 不需要 EV 证书 + 不需要 azure Trusted Signing；Tier 1 签了名之后用户跨大版本不再弹 SmartScreen。两件事解耦，代码签名只在值得花成本的场景花钱。
3. **失败模式不同**。Tier 1 失败 = 安装器回滚（NSIS 自带）；Tier 2 失败 = `last-good.json` 记的旧版还在，下次启动走老路径；Tier 3 失败 = 重 spawn 失败再退到 Tier 1 的回滚路径。三种失败路径独立，不会互相牵连。

---

## 3. Manifest 格式

服务端一份 JSON，所有客户端拉同一份。Tier 字段独立、互相不强制同号。

```jsonc
{
  "manifest_version": 1,
  "channel": "stable",                    // 后续可加 "beta"
  "released_at": "2026-09-15T08:00:00+08:00",

  // Tier 1：electron-updater 自带 latest.yml 协议，这里只是 reference
  // 真正的 NSIS 安装包元数据由 electron-builder 在 publish 时生成，
  // 我们不在 manifest 里再写一份，避免双源。

  // Tier 2：SPA + content-packs，独立可补丁
  "tier2": {
    "spa": {
      "version": "0.2.1",
      "url": "https://cdn.example.com/mhc-desktop/spa/0.2.1.tar.gz",
      "sha256": "f3a1...c0d",
      "size": 5242880
    },
    "content_packs": {
      "version": "2026-09-15",
      "url": "https://cdn.example.com/mhc-desktop/content-packs/2026-09-15.tar.gz",
      "sha256": "8b2c...e1a",
      "size": 1048576,
      // content-packs 走 overwrite=false 的语义（见 PACKAGING §3.6），
      // 这里只追加/替换新 unit，不删旧 unit
    }
  },

  // Tier 3：bundled backend
  "tier3": {
    "backend": {
      "version": "0.2.1",
      "url": "https://cdn.example.com/mhc-desktop/backend/0.2.1.tar.gz",
      "sha256": "1d4e...9f2",
      "size": 67108864,
      // 后端 = python.exe + python/Lib/site-packages + workspace wheel
      // PBS 升级（解释器版本变化）也走这个通道，但要额外携带 platform tag
      "pyth_on_tag": "20250814-x86_64-pc-windows-msvc-shared-install_only"
    }
  },

  "release_notes": "## 新增\n- ...\n\n## 修复\n- ...",
  "min_app_version": "0.1.0"               // 低于此版本必须先升 Tier 1
}
```

**字段解释**：

- `manifest_version`：manifest 自身的 schema 版本。客户端遇到不认识的 `manifest_version` 直接忽略、报"客户端过旧"。
- `tier2.content_packs.version` 用日期而非 semver：content packs 是纯数据、按发布日期语义最自然。
- `min_app_version`：低于此版本必须先走 Tier 1 把壳升上去，再能消费 Tier 2/3。这一条防的是"旧壳不认新 Tier 3 的 PBS tag"这种兼容性事故。

**自托管默认**：

```
DEFAULT_MANIFEST_URL = https://github.com/<owner>/<repo>/releases/latest/download/update.json
```

用户在 `mhc-desktop-prefs.json`（已有的 electron-store）里改 `manifestUrl` 即可指向自托管。空 = 用默认。

---

## 4. 状态机

```
                     ┌──────────────────────────────────────┐
                     │                                      │
                     ▼                                      │
  ┌─────────┐    checkManifest    ┌──────────────────┐      │
  │  IDLE   │ ─────────────────► │ UPDATE_AVAILABLE │      │
  │(启动后) │                     │ (有 Tier 2/3 可用) │      │
  └─────────┘                     └──────────┬───────┘      │
       ▲                                     │              │
       │ 用户选择 "Later"                      │ 用户 "Install now"
       │                                     ▼              │
       │                          ┌──────────────────┐      │
       │                          │   DOWNLOADING    │      │
       │                          │ (后台,不阻塞 UI)  │      │
       │                          └────────┬─────────┘      │
       │                                   │                │
       │                          校验失败 ▼                │
       │                          ┌──────────────────┐      │
       │                          │ DOWNLOAD_FAILED  │ ─────┘ (重试 3 次后回 IDLE)
       │                          └──────────────────┘
       │
       │  下次启动 / 用户点 "Restart now" (Tier 2/3)
       │                          ┌──────────────────┐
       └─────────────────────────│  STAGED          │
                                  │ (在 userData/    │
                                  │  staged-update/) │
                                  └────────┬─────────┘
                                           │
                                  启动时检测 ▼
                                  ┌──────────────────┐
                                  │  APPLYING        │
                                  │  原子替换        │
                                  │  extraResources/ │
                                  └────────┬─────────┘
                                           │
                                60s 内 ready? ──┐
                                  ┌────────┴────────┐
                                  ▼                 ▼
                          ┌─────────────┐    ┌─────────────┐
                          │ COMMIT      │    │ ROLLBACK    │
                          │ 写 last-good│    │ 恢复旧副本   │
                          └─────────────┘    └─────────────┘
```

**关键不变量**：

1. **UI 永远不阻塞**：manifest 检查和下载都在后台；用户任何时候都没看到"下载中"的全屏弹窗，只有托盘通知。
2. **应用替换只在启动早期发生**：在 `bootstrap()` 里、`mainWindow.loadURL()` 之前跑。SPA 一旦 paint 就不能再动文件。
3. **应用替换是原子的**：先解压到 `userData/staged-update/payload/`，校验完成后用 `rename`（同一卷上原子）覆盖 `resources/spa/dist` 和 `resources/content-packs`。Tier 3 走同样模式覆盖 `resources/backend`，但 Tier 3 不在启动早期做，而是发现 staged update 标记文件后让用户在托盘触发"reload backend"。
4. **回滚不丢用户数据**：只回滚安装包资源（`extraResources/`），不动 `userData/` 下任何文件（`~/.mhc-desktop/skills/` 用户自定义的不会被回滚覆盖）。

---

## 5. 文件布局

```
%LOCALAPPDATA%/mhc-desktop/                         # app.getPath('userData')
├── mhc-desktop.log                                  # 已存在
├── mhc-desktop-prefs.json                           # 已存在(electron-store)
│                                                    # 新增字段:
│                                                    #   manifestUrl?: string
│                                                    #   updateChannel: 'stable' | 'beta'
├── last-good.json                                    # 新增：上一次成功启动的版本快照
│                                                    # {
│                                                    #   "spa_version": "0.2.0",
│                                                    #   "content_packs_version": "2026-09-01",
│                                                    #   "backend_version": "0.2.0",
│                                                    #   "updated_at": "..."
│                                                    # }
├── staged-update/                                    # 新增：待应用的补丁
│   ├── manifest.json                                 # 下载下来的 manifest 副本
│   ├── tier2-spa.tar.gz                              # 待替换的 SPA 包
│   ├── tier2-content-packs.tar.gz
│   ├── tier3-backend.tar.gz
│   └── payload/                                      # 解压后的临时目录(应用成功后会清掉)
│       ├── spa/
│       ├── content-packs/
│       └── backend/
└── ... (其他用户数据)
```

**应用替换的步骤**（`bootstrap()` 里、`loadURL` 之前）：

```typescript
async function applyPendingUpdates(): Promise<void> {
  const staged = path.join(app.getPath('userData'), 'staged-update', 'manifest.json')
  if (!existsSync(staged)) return

  const manifest = JSON.parse(await fsp.readFile(staged, 'utf8'))
  const payload = path.join(path.dirname(staged), 'payload')
  const rp = process.resourcesPath
  if (!rp) return  // dev 模式不应该走到这里

  // 1. 校验 SHA256（manifest 里的 sha256 vs 解压后的实际哈希）
  // 2. 把当前 resources/spa/dist 复制到 resources/spa/dist.bak.<ts>
  // 3. rename(payload/spa, resources/spa/dist)
  // 4. 同样对 content-packs 和 backend（如果存在）
  // 5. 写 last-good.json
  // 6. 清掉 payload/ 和 .bak.* （成功后）
}
```

**回滚的步骤**（启动后 60s 内 `/ready` 未 200 或后端 exit code ≠ 0）：

```typescript
async function rollbackIfNeeded(): Promise<void> {
  const lastGood = readLastGood()
  const currentSpa = await sha256OfDir(path.join(process.resourcesPath!, 'spa'))
  if (currentSpa !== lastGood.spa_sha) {
    // 找到最新的 .bak.<ts> → rename 回去
    // 写一份 rollback-reason 到日志
    // 通知 renderer 显示"已回滚到 v0.x"提示
  }
}
```

---

## 6. UX

### 6.1 通知文案（中文，与现有 UI 一致）

- 托盘通知："有新版本可用：v0.2.1（后台下载中...）"
- 下载完成托盘通知："v0.2.1 已下载，下次启动时自动安装。立即重启？"
  - 按钮："立即重启" / "稍后" / "查看更新内容"
- 应用替换后下次启动的 splash 短暂显示（1.5s）："已更新到 v0.2.1"
- 回滚后通知："新版本启动失败，已自动回滚到 v0.2.0，日志已记录。"

### 6.2 用户控件

- **设置页 → 关于** 加一项 "自动更新"，可关闭（关闭后只检查、不下载、不提示）。
- **设置页 → 关于** 加一项 "更新通道"，stable / beta（默认 stable）。
- **设置页 → 关于** 加一项 "检查更新" 按钮，手动触发一次完整流程（manifest 检查 + 下载 + 提示安装）。

### 6.3 不做主动重启的边界

- 当前有活跃 SSE 流（用户在聊天）→ **不主动提示"立即重启"**，只提示"下次启动更新"。原因：SSE 流中途断开会触发 renderer 重新拉状态，体验更糟。
- 用户刚编辑某个 skill（未保存）→ 同样推迟。

实现方式：托盘通知时机选在 `before-quit` 的早期判定 + `mainWindow.on('hide')` 之后。

---

## 7. 国内网络适配

### 7.1 Manifest 镜像

默认 manifest URL 走 GH，但客户端启动第一次检查时若 5s 内未拿到响应，并发打三个镜像：

```
https://gh-proxy.com/<原始 URL>
https://mirror.ghproxy.com/<原始 URL>
https://npmmirror.com/mirrors/mhc-desktop/<channel>/update.json
```

任一返回 200 + 合法 JSON 即采用。结果缓存到 `last-good.json` 的 `manifest_source` 字段，下次默认走这个源（粘性）。这样客户端跑久了会"学会"最快的源。

### 7.2 不签名的边界

Tier 2/3 不签名 = HTTPS + SHA256 已经够。攻击者要伪造更新需要：

1. 控制我们的 CDN 域名（或控制 CDN 与客户端之间的中间人）；这是 HTTPS 防的。
2. 同时算出符合 manifest 里 sha256 的内容；SHA256 是抗碰撞的。

不签名的代价是：客户端不能从签名直接验证"这包确实是项目方发的"。但 Tier 2/3 包里没有可执行代码（SHA 校验天然防篡改），且 Tier 3 backend 跑在 sandbox 里（FastAPI 端口只开 127.0.0.1，攻击者能替换 backend.py 也不能远程触发）。结论：**Tier 2/3 不签名可接受**。

Tier 1 还是要签名：NSIS 安装器本身是可执行文件，用户双击会触发 SmartScreen。需要 Azure Trusted Signing 或 EV 证书。这一项在 PACKAGING.md §8.1 已经列出。

---

## 8. 与现有架构的衔接

### 8.1 不动 `mhc_desktop_backend` 的 Protocol 边界

更新机制是 Electron 主进程的事，后端 kernel 不需要知道。`mhc-desktop-deploy/build_default_app` 也不需要改。

如果未来要在后端侧加 `/api/v1/version` 这种端点（供 SPA 渲染"当前版本"），加在 `mhc_desktop_deploy` 里，**不进 kernel**。

### 8.2 复用现有 main.ts 已有能力

- **日志**：`appendLog()` 直接复用，加 `update` 前缀。
- **单实例锁**：更新下载不能在第二个进程跑，复用现有 `app.requestSingleInstanceLock()`。
- **托盘菜单**：加 3 项（"立即检查更新" / "更新通道" / "暂不更新"），复用 `tray.setContextMenu`。
- **`MHC_RESOURCES_PATH`** env：现有 main.ts 已经把这个传给后端；应用替换的代码也用这个变量知道 `extraResources/` 在哪。
- **close-pref electron-store**：复用，扩展 prefs 的字段（`manifestUrl` 等）而不是新建一个 store 文件。

### 8.3 复用 build 脚本产物

- `scripts/build-spa.sh` 已经把 SPA `dist/` 复制到 `mhc_desktop_backend/static/`，新增的"打 Tier 2 SPA 包"是同一个 dist 多打一份 tar.gz 到 `dist-update/spa-<version>.tar.gz`。
- `scripts/build-bundled-python.sh` 类似，新增打 Tier 3 backend tar.gz。
- `scripts/release.sh`（新增）：把 Tier 1 NSIS + Tier 2/3 tar.gz + manifest.json 一起上传到 GH release / 自托管。一个脚本管全套。

---

## 9. 实施阶段

按"投入产出比"和"出错成本"排序，**不做大爆炸**。

### Phase 1：Tier 2 单一通道（先做这个）

- 加 `manifest.json` 上传（GitHub Actions 或本地 `scripts/release.sh`）。
- 加 `src/updater/manifest.ts`：fetch + JSON.parse + SHA256 verify。
- 加 `src/updater/downloader.ts`：后台下载到 `staged-update/`，进度写日志。
- 加 `src/updater/applier.ts`：启动早期原子替换 `resources/spa/dist`。
- 加 `last-good.json` + 60s 内未 ready 回滚。
- 加托盘通知 + 设置页"检查更新"按钮。

**预计工作量**：1–2 天。验证一个常见 release flow：改一行 CSS → 打 SPA 包 → 推 GH → 启动旧版客户端 → 看到通知 → 重启 → 看到新版 UI。

### Phase 2：Tier 3 + content-packs

- 复用 Phase 1 的 manifest/downloader/applier。
- 后端 reload 逻辑：main.ts 加 `reloadBackend()`，先 SIGTERM child、等 5s、SIGKILL、rename `resources/backend/`、重 spawn。
- content-packs 的应用替换比 SPA 复杂：要走 PACKAGING §3.6 的 `materialize_bundled()` 路径，但要从 `userData/staged-update/payload/content-packs/` 读源而不是 `process.resourcesPath/content-packs/`。需要让后端启动时优先读 `MHC_STAGED_CONTENT_PATH` env（main.ts 在启动时设置）。

**预计工作量**：2–3 天。

### Phase 3：Tier 1 `electron-updater`

- 加 `electron-updater` 依赖 + 配置 `publish: { provider: 'github', ... }`。
- 触发条件：manifest 里的 `tier1.requires_update_from_current = true`，或者本地版本号跨 major。
- 代码签名：取决于公司决定走 Azure Trusted Signing 还是买 EV 证书。这一项卡外部，不阻塞 Phase 1/2 落地。

**预计工作量**：半天（如果签名已就绪）。

### Phase 4：自托管 + 国内镜像

- 把 manifest URL 抽成 prefs 字段。
- 启动时并发打多个镜像源 + 粘性缓存最快源。
- macOS / Linux 支持（`electron-updater` 自带，配置层面）。

**预计工作量**：1 天。

---

## 10. 验证清单

Phase 1 完成后必须跑过：

- [ ] **离线/在线切换**：manifest URL 404 时客户端不崩、保留旧版运行
- [ ] **下载中断**：拔网线 5 秒后恢复，下载能从断点续（HTTP Range）或从头开始
- [ ] **SHA256 不匹配**：故意上传一个坏 manifest，客户端拒绝应用、不污染 `extraResources/`
- [ ] **应用替换原子性**：替换过程中断电（kill -9 模拟），重启后 `resources/spa/dist` 要么全旧要么全新，没有半新半旧
- [ ] **回滚路径**：手动把新版 SPA 改成空白文件，重启后 60s 内 `/ready` 该 200（其实 SPA 没了后端仍能 ready，但 UI 会白屏 —— 这时回滚应触发）
- [ ] **托盘通知不打扰**：用户最小化到托盘后收到通知、不弹模态
- [ ] **设置页关闭"自动更新"**：客户端仍检查但不下载不通知
- [ ] **last-good.json 不丢**：删除 staged-update/ 后启动，仍能正常走老路径
- [ ] **用户数据不丢**：升级前后 `~/.mhc-desktop/skills/<用户自建>/` 内容不变
- [ ] **content-packs 幂等**：用户改过 bundled skill 后、升级到新版 bundled，**不**被新 bundled 覆盖（PACKAGING §3.6 已经锁死）

Phase 2+3 增加：

- [ ] **Tier 3 后端热替换**：用户在聊天中触发后端 reload，新版 backend 接替旧版、SSE 流断开 1s 后 renderer 自动重连
- [ ] **跨大版本 Tier 1**：manifest 标记 `requires_update_from_current`，旧版客户端**不**尝试 Tier 2/3，直接提示"需要先升级主程序"
- [ ] **代码签名后 SmartScreen 不再弹**：第一次安装有 1 次警告（无法避免），第二次开始消失

---

## 11. 已知未做的

- **差分更新（bsdiff）**：见 §1.2，等 Tier 2 流量上量再考虑。
- **增量备份 `extraResources/`**：当前 .bak.<ts> 方案一份备份占一份体积，长期来看 5 次更新后累计占 5 × 67 MB。可以做一个 LRU 清理（只保留最新 2 份）。Phase 1 不做，Phase 3 之后补。
- **强制回退（用户主动）**：用户能不能从 UI 选"我想回 v0.1.0"？当前不行，需要重新装 NSIS。可以做但 ROI 低。
- **更新策略 A/B 测试**：埋点"用户接受了多少次更新提示"——后续产品决策用，不是技术债。
- **Windows ARM64**：`mhc-desktop` 当前只 ship x64 NSIS。ARM64 Windows 用户（Surface Pro X 等）走 x64 emulation，性能略差但能跑。PBS aarch64-pc-windows-msvc 变体后续再补。

---

## 12. 跨文档索引

- [`PACKAGING.md`](PACKAGING.md) §3.5（`extraResources` 写入路径）、§3.6（content-packs 幂等语义）、§8（代码签名 + `electron-updater` 的初步列举）
- [`BUILTIN-CONTENT.md`](BUILTIN-CONTENT.md) — Tier 2 content-packs 应用替换走的就是它定义的 schema
- [`../mhc-desktop-deploy/README.md`](../mhc-desktop-deploy/README.md) — 如果 Phase 2 加 `/api/v1/version` 端点，落在这里
