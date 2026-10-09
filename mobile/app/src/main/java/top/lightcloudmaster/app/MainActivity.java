package top.lightcloudmaster.app;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.ContentValues;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;

/**
 * 拾光云上 WebView 客户端：打开即进入 https://www.lightcloudmaster.top/ 。
 *
 * 与网站功能的对应关系（改动前先读）：
 * - 对话流（POST /api/chat/stream，fetch + ReadableStream 逐帧解析）→ 现代 WebView
 *   原生支持；旧内核自动走页面内已内置的 r.text() 整段降级，无需 App 干预。
 * - localStorage 存取（注册态、未成年标记）→ 开启 DOM Storage。
 * - 隐私数据导出（前端 blob + a.download）→ WebView 不会自行处理 blob 下载，
 *   由 {@link BlobSaver} 经 JS 桥取出内容并存入系统「下载/LightCloudMaster」。
 * - 深色模式：站点自带 prefers-color-scheme 样式，App 只负责让 WebView 跟随系统。
 */
public class MainActivity extends Activity {

    private static final String SITE_URL = "https://www.lightcloudmaster.top/";
    /** 站内主域：这两个域名内的链接一律留在 App 内打开。 */
    private static final String SITE_HOST = "lightcloudmaster.top";
    private static final String OFFLINE_PAGE = "file:///android_asset/offline.html";

    private WebView webView;

    @SuppressLint({"SetJavaScriptEnabled", "ForceDark"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        setContentView(webView);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);            // localStorage / sessionStorage
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);              // 尊重页面 viewport meta
        s.setLoadWithOverviewMode(true);
        s.setMediaPlaybackRequiresUserGesture(false); // 未来若加提示音，无需用户先点屏幕
        // 跟随系统深色模式，让站点的 prefers-color-scheme 生效。
        // setForceDark 自 API 29、setAlgorithmicDarkeningAllowed 自 API 33 才存在。
        if (Build.VERSION.SDK_INT >= 33) {
            s.setAlgorithmicDarkeningAllowed(true);
        } else if (Build.VERSION.SDK_INT >= 29) {
            s.setForceDark(WebSettings.FORCE_DARK_AUTO);
        }

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme() == null ? "" : uri.getScheme();
                if (scheme.equals("http") || scheme.equals("https")) {
                    String host = uri.getHost() == null ? "" : uri.getHost();
                    return !host.equals(SITE_HOST) && !host.endsWith("." + SITE_HOST)
                            ? openExternally(uri)   // 意外出现的站外链接交给系统浏览器
                            : false;                // 站内导航留在 WebView
                }
                return openExternally(uri);        // mailto: / tel: / intent: 等
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                // 只处理主文档加载失败（子资源 404 不算断网），展示本地重试页。
                if (!request.isForMainFrame()
                        || request.getUrl().toString().startsWith("file:")) {
                    return;
                }
                String target = Uri.encode(request.getUrl().toString());
                view.loadUrl(OFFLINE_PAGE + "?u=" + target);
            }

            // 渲染进程崩溃后 WebView 已不可用：重建 Activity，避免永久白屏。
            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                recreate();
                return true;
            }
        });

        webView.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimeType, long contentLength) {
                if (url.startsWith("blob:")) {
                    fetchBlobIntoSaver(url);       // 隐私导出（前端 blob 下载）
                } else if (url.startsWith("http")) {
                    DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                    if (dm != null) {
                        dm.enqueue(new DownloadManager.Request(Uri.parse(url))
                                .setNotificationVisibility(
                                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED));
                    }
                }
            }
        });

        webView.addJavascriptInterface(new BlobSaver(), "LCMBlob");
        CookieManager.getInstance().setAcceptCookie(true);

        // 返回键回退网页历史时由 onBackPressed 处理；冷启动只加载首页。
        webView.loadUrl(savedInstanceState == null ? SITE_URL
                : savedInstanceState.getString("url", SITE_URL));
    }

    /** 尝试用系统其他 App 打开；打不开就直接吞掉（返回 true），不打断用户。 */
    private boolean openExternally(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception ignored) {
            Toast.makeText(this, R.string.no_external_app, Toast.LENGTH_SHORT).show();
        }
        return true;
    }

    /**
     * WebView 把 blob: 下载原样丢给 onDownloadStart，但无法直接读取。
     * 在页面上下文里 fetch 该 blob → base64 → 交给 {@link BlobSaver} 落盘。
     */
    private void fetchBlobIntoSaver(String blobUrl) {
        // blob 地址只含安全字符（协议 + uuid），双保险再转义一次引号与反斜杠。
        String safeUrl = blobUrl.replace("\\", "\\\\").replace("'", "\\'");
        String js = "(function(){var u='" + safeUrl + "';"
                + "fetch(u).then(function(r){return r.blob();}).then(function(b){"
                + "var n=(b.type.indexOf('json')>=0)?'lightcloudmaster-export.json'"
                + ":(b.type.split('/')[1]?'download.'+b.type.split('/')[1]:'download.bin');"
                + "var f=new FileReader();"
                + "f.onload=function(){var d=String(f.result).split(',')[1];"
                + "LCMBlob.save(n,b.type,d);};"
                + "f.onerror=function(){LCMBlob.save('', '', null);};"
                + "f.readAsDataURL(b);});})();";
        webView.evaluateJavascript(js, null);
    }

    /** JS 桥：接收 blob 的名字/类型/内容并保存（JavascriptInterface 强制公开方法，保持仅此一个）。 */
    private class BlobSaver {
        @JavascriptInterface
        public void save(String name, String mime, String dataB64) {
            runOnUiThread(() -> {
                try {
                    if (dataB64 == null) {
                        throw new IllegalArgumentException("read failed");
                    }
                    String safeName = (name == null || name.isEmpty())
                            ? "download.bin" : name;
                    String safeMime = (mime == null || mime.isEmpty())
                            ? "application/octet-stream" : mime;
                    byte[] data = Base64.decode(dataB64, Base64.DEFAULT);
                    String where = saveToDownloads(safeName, safeMime, data);
                    Toast.makeText(MainActivity.this,
                            getString(R.string.saved_to, where), Toast.LENGTH_LONG).show();
                } catch (Exception e) {
                    Toast.makeText(MainActivity.this,
                            R.string.save_failed, Toast.LENGTH_LONG).show();
                }
            });
        }

        private String saveToDownloads(String name, String mime, byte[] data) throws Exception {
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                v.put(MediaStore.MediaColumns.RELATIVE_PATH,
                        Environment.DIRECTORY_DOWNLOADS + "/LightCloudMaster");
                v.put(MediaStore.MediaColumns.IS_PENDING, 1);
                Uri uri = getContentResolver()
                        .insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (uri == null) {
                    throw new IllegalStateException("MediaStore insert failed");
                }
                try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                    os.write(data);
                }
                v.clear();
                v.put(MediaStore.MediaColumns.IS_PENDING, 0);
                getContentResolver().update(uri, v, null, null);
                return Environment.DIRECTORY_DOWNLOADS + "/LightCloudMaster/" + name;
            }
            // Android 8.x/9：无存储权限也可写应用外部专属目录，路径如实告知用户。
            File dir = getExternalFilesDir(Environment.DIRECTORY_DOCUMENTS);
            if (dir == null) {
                dir = getFilesDir();
            }
            File out = new File(dir, name);
            try (FileOutputStream fos = new FileOutputStream(out)) {
                fos.write(data);
            }
            return out.getAbsolutePath();
        }
    }

    /** 记住渲染进程崩溃重建前的位置，以及进程被杀后的恢复。 */
    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        if (webView != null) {
            outState.putString("url", webView.getUrl());
        }
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onPause() {
        if (webView != null) {
            webView.onPause();
            CookieManager.getInstance().flush();
        }
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.onResume();
        }
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }
}
