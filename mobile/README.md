# 拾光云上 · Android WebView 客户端

像 DeepSeek 客户端一样的最薄封装：点开 App 即进入
`https://www.lightcloudmaster.top/`，全部业务逻辑都在网站上，App 只负责
「容器」该做的事。**零第三方依赖**（无 AndroidX / 无任何 Maven 库），
纯系统 `android.webkit.WebView`，单个 Activity。

## 功能对照（为什么只有这点代码）

| 站点能力 | App 侧处理 |
|---|---|
| 对话流 `POST /api/chat/stream`（fetch + ReadableStream 逐帧） | WebView 原生支持；旧内核自动走前端已内置的整段解析降级 |
| `localStorage` 注册态 / 未成年标记 | `setDomStorageEnabled(true)` |
| 隐私数据导出（blob + `a.download`） | `DownloadListener` + JS 桥（`LCMBlob`）取出 blob 存入系统「下载/LightCloudMaster」 |
| 深色模式（`prefers-color-scheme`） | 跟随系统：33+ `setAlgorithmicDarkeningAllowed`，旧机型 `setForceDark(AUTO)` |
| 断网 | 本地 `offline.html` 重试页（仅主文档失败时触发） |
| 返回键 | 先回退网页历史，到底才退出 |
| 渲染进程崩溃 | `onRenderProcessGone` 重建 Activity，避免白屏 |
| 意外站外链接 / `mailto:` 等 | 交系统浏览器或对应应用打开 |

## 目录

```
mobile/
├── app/src/main/java/top/lightcloudmaster/app/MainActivity.java   # 全部逻辑
├── app/src/main/AndroidManifest.xml                               # 仅 INTERNET 权限
├── app/src/main/assets/offline.html                               # 断网重试页
├── app/src/main/res/                                              # 主题/字符串/自适应图标
├── scripts/make-keystore.cmd                                      # 生成签名密钥（换钥用）
├── gradlew.bat / gradle/                                          # Gradle Wrapper（镜像源）
├── release/LightCloudMaster-v1.0.0.apk                            # 当前交付的 APK
└── README.md
```

## 构建

### 方式一：本仓库自带的 Gradle Wrapper（需 JDK 17，无需 Android Studio）

已生成 `gradlew` / `gradlew.bat`，分发地址指向腾讯镜像（本机网络 gradle.org 不可达）。
首次构建时 `local.properties` 已指向仓库外层 `.toolkit/android-sdk`；若将来在其他
机器上构建，装好 Android SDK 后改写 `local.properties` 的 `sdk.dir` 即可，或直接
用 Android Studio 打开让它自动生成。

```cmd
cd mobile
gradlew.bat assembleRelease
```

产物：`app/build/outputs/apk/release/app-release.apk`（同时复制一份到
`mobile/release/LightCloudMaster-v<版本号>.apk`）。

### 方式二：Android Studio

直接用 Android Studio 打开 `mobile/` 目录，Gradle 同步后 Run / Build 即可。

### 关于 release 签名

release 构建使用 `app/keystore.properties` + `app/lcm-release.keystore` 签名。
这两个文件已被 `.gitignore` 排除——**密钥泄漏等于任何人都能给你的用户推送冒名
升级包**，绝不能进公开仓库，请另行备份（如密码管理器）。

> 本工作区已生成一对密钥：alias `lcm`，密码见 `app/keystore.properties`。
> 换新密钥只需重新生成（`scripts\make-keystore.cmd`）并更新该文件；
> 但已安装旧版的用户将无法覆盖升级，只能卸载重装。
> 密钥缺失时构建自动退回 debug 签名，仅供本机试装。

## 常改项

| 需求 | 位置 |
|---|---|
| 站点地址 | `MainActivity.SITE_URL` / `SITE_HOST` |
| App 名称 / 图标 | `res/values/strings.xml` / `res/drawable/ic_launcher_*.xml`、`res/mipmap-anydpi-v26/` |
| 版本号 | `app/build.gradle` 的 `versionCode` / `versionName` |

## 约束

- minSdk 26（Android 8.0）：自适应图标纯矢量即可，无需多套 PNG；
  targetSdk 34。
- 仅 `INTERNET` 权限；导出文件走 `MediaStore`（29+）或应用外部目录（8.x/9），
  不申请存储权限。
- HTTPS-only：清单未开 cleartext，站点本身全站 HTTPS。
