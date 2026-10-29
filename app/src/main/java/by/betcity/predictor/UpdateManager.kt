package by.betcity.predictor

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.webkit.WebView
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/** Проверка, загрузка и установка обновлений APK с сайта проекта. */
class UpdateManager(
    private val activity: Activity,
    private val webView: WebView,
) {
    @Volatile
    private var downloading = false

    private fun currentPackage(): JSONObject {
        @Suppress("DEPRECATION")
        val info = activity.packageManager.getPackageInfo(activity.packageName, 0)
        return JSONObject()
            .put("ok", true)
            .put("version_code", info.versionCode)
            .put("version_name", info.versionName ?: "")
            .put("package", activity.packageName)
    }

    fun info(): String = currentPackage().toString()

    fun check(manifestUrl: String, token: String, manual: Boolean): String {
        val url = manifestUrl.trim()
        if (!url.startsWith("https://") && !url.startsWith("http://")) {
            return error("Некорректный адрес манифеста обновлений.")
        }
        Thread {
            try {
                val manifest = fetchJson(url, token)
                val current = currentPackage()
                val latestCode = manifest.intOf("version_code", "versionCode", "code")
                val latestName = manifest.stringOf("version_name", "versionName", "name")
                val available = latestCode > current.optInt("version_code", 0)
                val apkUrl = resolveUrl(url, manifest.stringOf("url", "apk_url", "apkUrl"))
                emit(
                    JSONObject()
                        .put("type", "check")
                        .put("ok", true)
                        .put("manual", manual)
                        .put("checked", true)
                        .put("available", available)
                        .put("current_code", current.optInt("version_code", 0))
                        .put("current_name", current.optString("version_name"))
                        .put("version_code", latestCode)
                        .put("version_name", latestName)
                        .put("url", apkUrl)
                        .put("sha256", manifest.stringOf("sha256", "sha"))
                        .put("size", manifest.longOf("size", "bytes"))
                        .put("notes", manifest.stringOf("notes", "changelog"))
                        .put("mandatory", manifest.optBoolean("mandatory", false))
                        .put("published_at", manifest.stringOf("published_at", "date"))
                        .put("min_sdk", manifest.intOf("min_sdk"))
                )
            } catch (t: Throwable) {
                emit(
                    JSONObject()
                        .put("type", "check")
                        .put("ok", false)
                        .put("manual", manual)
                        .put("checked", true)
                        .put("error", friendly(t))
                )
            }
        }.start()
        return JSONObject().put("ok", true).put("started", true).toString()
    }

    fun download(url: String, sha256: String, version: String, token: String): String {
        if (!url.startsWith("https://") && !url.startsWith("http://")) {
            return error("В манифесте указан некорректный адрес APK.")
        }
        if (downloading) {
            return error("Загрузка уже идёт.")
        }
        val expected = sha256.trim().lowercase()
        val dir = updatesDir()
        val safeVersion = version.replace(Regex("[^0-9A-Za-z._-]"), "_")
            .ifBlank { "latest" }
        val suffix = expected.take(8).ifBlank { "apk" }
        val target = File(dir, "predictor-$safeVersion-$suffix.apk")

        Thread {
            downloading = true
            try {
                dir.mkdirs()
                if (target.isFile && expected.isNotEmpty() &&
                    sha256(target) == expected
                ) {
                    emit(downloadEvent(true, target, reused = true))
                    return@Thread
                }
                if (target.exists()) target.delete()

                val connection = open(url, token)
                val total = connection.contentLengthLong.coerceAtLeast(0L)
                connection.inputStream.use { input ->
                    FileOutputStream(target).use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var written = 0L
                        var lastEmit = 0L
                        while (true) {
                            val read = input.read(buffer)
                            if (read <= 0) break
                            output.write(buffer, 0, read)
                            written += read
                            val now = SystemClock.elapsedRealtime()
                            if (now - lastEmit >= 300 || written == total) {
                                lastEmit = now
                                val percent = if (total > 0) {
                                    (written * 100 / total).toInt()
                                } else 0
                                emit(
                                    JSONObject()
                                        .put("type", "progress")
                                        .put("downloaded", written)
                                        .put("total", total)
                                        .put("percent", percent)
                                )
                            }
                        }
                        output.fd.sync()
                    }
                }
                connection.disconnect()

                if (expected.isNotEmpty() && sha256(target) != expected) {
                    target.delete()
                    throw IllegalStateException(
                        "Контрольная сумма APK не совпала. Файл удалён."
                    )
                }
                if (target.length() <= 0L) {
                    target.delete()
                    throw IllegalStateException("Сайт вернул пустой файл.")
                }
                emit(downloadEvent(true, target, reused = false))
            } catch (t: Throwable) {
                emit(
                    JSONObject()
                        .put("type", "download")
                        .put("ok", false)
                        .put("error", friendly(t))
                )
            } finally {
                downloading = false
            }
        }.start()
        return JSONObject().put("ok", true).put("started", true).toString()
    }

    fun install(path: String): String {
        val dir = updatesDir().canonicalFile
        val file = File(path).canonicalFile
        if (!file.isFile || !file.path.startsWith(dir.path + File.separator)) {
            return error("Скачанный APK не найден. Загрузите обновление заново.")
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !activity.packageManager.canRequestPackageInstalls()
        ) {
            try {
                val intent = Intent(
                    android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.packageName),
                )
                activity.startActivity(intent)
            } catch (t: Throwable) {
                return error("Разрешите установку из этого источника в настройках Android.")
            }
            emit(
                JSONObject()
                    .put("type", "install")
                    .put("ok", false)
                    .put("permission", true)
                    .put("error", "Нужно разрешить установку приложений из этого источника.")
            )
            return JSONObject().put("ok", true).put("permission", true).toString()
        }
        return try {
            val uri = FileProvider.getUriForFile(
                activity, activity.packageName + ".fileprovider", file
            )
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            activity.startActivity(intent)
            JSONObject().put("ok", true).put("started", true).toString()
        } catch (t: Throwable) {
            error("Не удалось открыть установщик: ${t.message}")
        }
    }

    private fun updatesDir(): File = File(activity.cacheDir, "updates")

    private fun open(url: String, token: String): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 15000
        connection.readTimeout = 60000
        connection.instanceFollowRedirects = true
        connection.setRequestProperty("Accept", "application/json, application/octet-stream")
        connection.setRequestProperty("User-Agent", "Predictor-Android-Updater")
        if (token.isNotBlank()) {
            connection.setRequestProperty("Authorization", "Bearer $token")
        }
        val code = connection.responseCode
        if (code == 401) {
            connection.disconnect()
            throw IllegalStateException("Сайт отклонил токен доступа (401).")
        }
        if (code >= 400) {
            connection.disconnect()
            throw IllegalStateException("Сайт вернул $code.")
        }
        return connection
    }

    private fun fetchJson(url: String, token: String): JSONObject {
        val connection = open(url, token)
        try {
            val text = connection.inputStream.bufferedReader(Charsets.UTF_8).use {
                it.readText()
            }
            if (text.length > 1024 * 1024) {
                throw IllegalStateException("Слишком большой ответ сайта.")
            }
            val data = JSONObject(text)
            if (!data.optBoolean("ok", true)) {
                throw IllegalStateException(
                    data.optString("error", "Сайт не отдал данные об обновлении.")
                )
            }
            return data
        } finally {
            connection.disconnect()
        }
    }

    private fun resolveUrl(base: String, value: String): String {
        if (value.isBlank()) return ""
        return try {
            URL(URL(base), value).toString()
        } catch (t: Throwable) {
            value
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun downloadEvent(ok: Boolean, file: File, reused: Boolean): JSONObject =
        JSONObject()
            .put("type", "download")
            .put("ok", ok)
            .put("path", file.absolutePath)
            .put("size", file.length())
            .put("reused", reused)

    private fun error(message: String): String =
        JSONObject().put("ok", false).put("error", message).toString()

    private fun friendly(t: Throwable): String {
        val message = t.message?.trim().orEmpty()
        return message.ifBlank { "Ошибка обновления: ${t.javaClass.simpleName}" }
    }

    private fun emit(event: JSONObject) {
        val json = event.toString()
        val script = "window.PredictorUpdate && window.PredictorUpdate.onEvent(" +
            JSONObject.quote(json) + ");"
        webView.post {
            try {
                webView.evaluateJavascript(script, null)
            } catch (t: Throwable) {
                android.util.Log.w("Predictor", "Update event failed", t)
            }
        }
    }

    private fun JSONObject.stringOf(vararg keys: String): String {
        for (key in keys) {
            val value = optString(key, "")
            if (value.isNotBlank()) return value
        }
        return ""
    }

    private fun JSONObject.intOf(vararg keys: String): Int {
        for (key in keys) {
            if (has(key) && !isNull(key)) {
                return optInt(key, 0)
            }
        }
        return 0
    }

    private fun JSONObject.longOf(vararg keys: String): Long {
        for (key in keys) {
            if (has(key) && !isNull(key)) {
                return optLong(key, 0L)
            }
        }
        return 0L
    }
}
