package com.mark56.companion

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object BatterySync {
    private const val UNIQUE_WORK = "mark56-companion-battery-sync"

    fun enable(context: Context) {
        val request = PeriodicWorkRequestBuilder<BatterySyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            UNIQUE_WORK, ExistingPeriodicWorkPolicy.UPDATE, request
        )
        CompanionSettings(context).setBatterySyncEnabled(true)
    }

    fun disable(context: Context) {
        CompanionSettings(context).setBatterySyncEnabled(false)
        WorkManager.getInstance(context).cancelUniqueWork(UNIQUE_WORK)
    }
}
