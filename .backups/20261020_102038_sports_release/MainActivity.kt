package by.betcity.predictor

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.chaquo.python.Python
import java.io.File

class MainActivity : Activity() {

    private lateinit var webView: WebView
    private var pendingSaveName: String? = null
    private var pendingSaveContent: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Статус-бар не показываем и красим его в цвет приложения.
        @Suppress("DEPRECATION")
        run {
            window.statusBarColor = APP_BACKGROUND
            window.navigationBarColor = APP_BACKGROUND
            window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
        }

        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.allowFileAccess = true
            settings.setSupportZoom(false)
            settings.textZoom = 100
            webViewClient = WebViewClient()
            webChromeClient = object : WebChromeClient() {
                override fun onJsConfirm(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    result: JsResult?
                ): Boolean {
                    AlertDialog.Builder(this@MainActivity)
                        .setMessage(message)
                        .setPositiveButton("Да") { _, _ -> result?.confirm() }
                        .setNegativeButton("Отмена") { _, _ -> result?.cancel() }
                        .setOnCancelListener { result?.cancel() }
                        .show()
                    return true
                }

                override fun onJsAlert(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    result: JsResult?
                ): Boolean {
                    AlertDialog.Builder(this@MainActivity)
                        .setMessage(message)
                        .setPositiveButton("OK") { _, _ -> result?.confirm() }
                        .setOnCancelListener { result?.cancel() }
                        .show()
                    return true
                }
            }
            addJavascriptInterface(Bridge(), "PyApp")
            setBackgroundColor(0xFF0F1115.toInt())
            loadUrl("file:///android_asset/www/index.html")
        }
        setContentView(webView)
        requestNotificationPermission()

        // Прогрев Python: импорт движка занимает время, лучше сделать это
        // до первого обращения из интерфейса.
        Thread {
            try {
                py().getModule("engine_api")
            } catch (t: Throwable) {
                android.util.Log.e("Predictor", "Python init failed", t)
            }
        }.start()
    }

    /** Скрывает статус-бар во всех состояниях окна. */
    private fun hideStatusBar() {
        val controller = WindowInsetsControllerCompat(window, window.decorView)
        controller.hide(WindowInsetsCompat.Type.statusBars())
        controller.systemBarsBehavior =
            WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE

        @Suppress("DEPRECATION")
        run {
            window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
            window.decorView.systemUiVisibility = (
                View.SYSTEM_UI_FLAG_FULLSCREEN
                    or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                )
        }
    }

    override fun onResume() {
        super.onResume()
        hideStatusBar()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideStatusBar()
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(
                arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS
            )
        }
    }

    private fun py(): Python = Python.getInstance()

    private fun call(name: String, vararg args: Any?): String {
        return try {
            val module = py().getModule("engine_api")
            module.callAttr(name, *args).toString()
        } catch (t: Throwable) {
            val message = (t.message ?: t.toString())
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", " ")
                .replace("\r", " ")
            """{"ok":false,"error":"$message"}"""
        }
    }

    inner class Bridge {

        // ---------------- состояние ----------------
        @JavascriptInterface
        fun state(): String = call("api_state")

        @JavascriptInterface
        fun start(): String {
            val result = call("api_start")
            EngineService.start(this@MainActivity)
            return result
        }

        @JavascriptInterface
        fun stop(): String {
            val result = call("api_stop")
            EngineService.stop(this@MainActivity)
            return result
        }

        @JavascriptInterface
        fun runOnce(): String = call("api_run_once")

        @JavascriptInterface
        fun version(): String = call("api_version")

        // ---------------- настройки ----------------
        @JavascriptInterface
        fun settings(): String = call("api_settings")

        @JavascriptInterface
        fun saveSettings(json: String): String = call("api_save_settings", json)

        @JavascriptInterface
        fun resetSettings(): String = call("api_reset_settings")

        @JavascriptInterface
        fun setSport(sport: String): String = call("api_set_sport", sport)

        // ---------------- логи ----------------
        @JavascriptInterface
        fun logs(sinceId: Int, limit: Int, level: String, search: String): String =
            call("api_logs", sinceId, limit, level, search)

        @JavascriptInterface
        fun clearLogs(): String = call("api_clear_logs")

        @JavascriptInterface
        fun errors(limit: Int): String = call("api_errors", limit)

        // ---------------- очередь ----------------
        @JavascriptInterface
        fun queue(): String = call("api_queue")

        @JavascriptInterface
        fun refreshQueue(): String = call("api_refresh_queue")

        @JavascriptInterface
        fun clearProcessed(): String = call("api_clear_processed")

        // ---------------- прогнозы и статистика ----------------
        @JavascriptInterface
        fun predictions(limit: Int, sport: String): String =
            call("api_predictions", limit, sport)

        @JavascriptInterface
        fun results(start: String, end: String, search: String, status: String,
                    limit: Int, sport: String): String =
            call("api_results", start, end, search, status, limit, sport)

        @JavascriptInterface
        fun constructor(sport: String): String = call("api_constructor", sport)

        @JavascriptInterface
        fun saveConstructor(json: String): String = call("api_save_constructor", json)

        @JavascriptInterface
        fun setAlgorithmMode(mode: String): String = call("api_set_algorithm_mode", mode)

        @JavascriptInterface
        fun testConstructor(payload: String, limit: Int): String =
            call("api_test_constructor", payload, limit)

        @JavascriptInterface
        fun analyzer(payload: String): String = call("api_analyzer", payload)

        @JavascriptInterface
        fun stats(): String = call("api_stats")

        @JavascriptInterface
        fun resetStats(): String = call("api_reset_stats")

        @JavascriptInterface
        fun testConnection(): String = call("api_test_connection")

        // ---------------- данные ----------------
        @JavascriptInterface
        fun exportData(kind: String): String = call("api_export", kind)

        @JavascriptInterface
        fun clearData(what: String): String = call("api_clear_data", what)

        @JavascriptInterface
        fun shareFile(name: String, mime: String, content: String) {
            runOnUiThread {
                try {
                    val dir = File(cacheDir, "exports").apply { mkdirs() }
                    val file = File(dir, name)
                    file.writeText(content)
                    val uri = FileProvider.getUriForFile(
                        this@MainActivity, "$packageName.fileprovider", file
                    )
                    val intent = Intent(Intent.ACTION_SEND).apply {
                        type = mime
                        putExtra(Intent.EXTRA_STREAM, uri)
                        putExtra(Intent.EXTRA_SUBJECT, name)
                        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    }
                    startActivity(Intent.createChooser(intent, "Отправить $name"))
                } catch (t: Throwable) {
                    toast("Не удалось поделиться: ${t.message}")
                }
            }
        }

        @JavascriptInterface
        fun saveFile(name: String, mime: String, content: String) {
            runOnUiThread {
                try {
                    pendingSaveName = name
                    pendingSaveContent = content
                    val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = mime
                        putExtra(Intent.EXTRA_TITLE, name)
                    }
                    @Suppress("DEPRECATION")
                    startActivityForResult(intent, REQUEST_SAVE)
                } catch (t: Throwable) {
                    toast("Не удалось сохранить: ${t.message}")
                }
            }
        }

        @JavascriptInterface
        fun toast(message: String) {
            runOnUiThread { this@MainActivity.toast(message) }
        }

        @JavascriptInterface
        fun notifySignal(title: String, text: String) {
            EngineService.notify(this@MainActivity, title, text)
        }

        @JavascriptInterface
        fun keepScreenOn(enabled: Boolean) {
            runOnUiThread {
                if (enabled) {
                    window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                } else {
                    window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                }
            }
        }

        @JavascriptInterface
        fun platform(): String = "android-${Build.VERSION.SDK_INT}"
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_SAVE) return
        if (resultCode != RESULT_OK) {
            pendingSaveName = null
            pendingSaveContent = null
            return
        }
        val uri: Uri = data?.data ?: return
        val content = pendingSaveContent ?: return
        try {
            contentResolver.openOutputStream(uri)?.use { stream ->
                stream.write(content.toByteArray(Charsets.UTF_8))
            }
            toast("Сохранено: ${pendingSaveName ?: "файл"}")
        } catch (t: Throwable) {
            toast("Ошибка записи: ${t.message}")
        } finally {
            pendingSaveName = null
            pendingSaveContent = null
        }
    }

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    override fun onBackPressed() {
        webView.evaluateJavascript(
            "(function(){ if (window.appBack && window.appBack()) return true; return false; })()"
        ) { result ->
            // WebView возвращает JSON: "true" или "false".
            if (result == null || result.trim() != "true") {
                @Suppress("DEPRECATION")
                super.onBackPressed()
            }
        }
    }

    companion object {
        private const val REQUEST_SAVE = 1001
        private const val REQUEST_NOTIFICATIONS = 1002
        private val APP_BACKGROUND = 0xFF0F1115.toInt()
    }
}
