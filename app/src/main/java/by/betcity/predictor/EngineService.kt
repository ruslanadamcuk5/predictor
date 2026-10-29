package by.betcity.predictor

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.chaquo.python.Python

/**
 * Держит процесс живым, пока работает движок прогнозирования.
 * Сама логика выполняется в Python-потоке; сервис нужен, чтобы
 * Android не выгрузил приложение из памяти.
 */
class EngineService : Service() {

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, buildNotification("Движок работает", "Сканирование линии Betcity"))
        // Если движок был запущен до перезапуска процесса — поднимаем его.
        Thread {
            try {
                Python.getInstance().getModule("engine_api").callAttr("api_autostart")
            } catch (t: Throwable) {
                android.util.Log.e("Predictor", "autostart failed", t)
            }
        }.start()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun buildNotification(title: String, text: String): Notification {
        val openIntent = Intent(this, MainActivity::class.java)
        val pending = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true)
            .setContentIntent(pending)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(
                CHANNEL_ID, "Движок прогнозирования", NotificationManager.IMPORTANCE_LOW
            ).apply { description = "Уведомление о работе движка" }
            manager.createNotificationChannel(channel)
        }
    }

    companion object {
        private const val CHANNEL_ID = "engine_status"
        private const val SIGNAL_CHANNEL_ID = "engine_signals"
        private const val NOTIFICATION_ID = 4101

        @JvmStatic
        fun start(context: Context) {
            val intent = Intent(context, EngineService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        @JvmStatic
        fun stop(context: Context) {
            context.stopService(Intent(context, EngineService::class.java))
        }

        @JvmStatic
        fun notify(context: Context, title: String, text: String) {
            val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val channel = NotificationChannel(
                    SIGNAL_CHANNEL_ID, "Сигналы", NotificationManager.IMPORTANCE_DEFAULT
                )
                manager.createNotificationChannel(channel)
            }
            val notification = NotificationCompat.Builder(context, SIGNAL_CHANNEL_ID)
                .setContentTitle(title)
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setAutoCancel(true)
                .build()
            manager.notify(System.currentTimeMillis().toInt(), notification)
        }
    }
}
