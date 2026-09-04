package com.deniscerri.ytdl.core

import android.content.Context
import java.io.File
import java.io.IOException

/**
 * Installs YTDLnis-owned yt-dlp extractor plugins beside the portable yt-dlp binary.
 *
 * yt-dlp automatically discovers packages under:
 *   <binary dir>/yt-dlp-plugins/<package>/yt_dlp_plugins/extractor/
 *
 * Keeping these extractors outside the bundled yt-dlp zip lets YTDLnis fill small
 * site-specific gaps without forking or rebuilding the entire yt-dlp runtime.
 */
object SocialExtractorPluginInstaller {
    private const val PLUGIN_ROOT = "yt-dlp-plugins/ytdlnis-social/yt_dlp_plugins/extractor"

    private val bundledPlugins = listOf(
        "social_extractors/instagram_audio.py" to "instagram_audio.py",
        "social_extractors/social_redirects.py" to "social_redirects.py",
        "social_extractors/threads.py" to "threads.py",
    )

    @Throws(IOException::class)
    fun install(context: Context) {
        val ytdlpDir = File(
            context.noBackupFilesDir,
            "${RuntimeManager.BASENAME}/${RuntimeManager.ytdlpDirName}",
        )
        val extractorDir = File(ytdlpDir, PLUGIN_ROOT).apply {
            if (!exists() && !mkdirs()) {
                throw IOException("Could not create yt-dlp plugin directory: $absolutePath")
            }
        }

        bundledPlugins.forEach { (assetPath, outputName) ->
            installAsset(context, assetPath, File(extractorDir, outputName))
        }
    }

    private fun installAsset(context: Context, assetPath: String, destination: File) {
        val bundledBytes = context.assets.open(assetPath).use { it.readBytes() }
        if (destination.exists() && destination.readBytes().contentEquals(bundledBytes)) {
            return
        }

        val temp = File(destination.parentFile, ".${destination.name}.tmp")
        temp.writeBytes(bundledBytes)

        // Android's File.renameTo does not replace an existing destination reliably.
        // Delete only after the complete replacement has been written to the temp file.
        if (destination.exists() && !destination.delete()) {
            temp.delete()
            throw IOException("Could not replace yt-dlp plugin: ${destination.absolutePath}")
        }

        if (!temp.renameTo(destination)) {
            // Cross-filesystem rename should not happen here, but keep a safe fallback.
            destination.writeBytes(bundledBytes)
            temp.delete()
        }
    }
}
