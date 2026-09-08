package com.deniscerri.ytdl.core.models

/**
 * Prevents yt-dlp command combinations that are known to fail only after the
 * media has already been downloaded and converted.
 *
 * In particular, yt-dlp cannot embed thumbnails into WAV files. Letting that
 * combination through makes a successful WAV extraction look like a failed
 * download during post-processing.
 */
internal object YTDLCommandCompatibility {
    private val audioFormatOutputExtensions = mapOf(
        "aac" to "m4a",
        "alac" to "m4a",
        "flac" to "flac",
        "m4a" to "m4a",
        "mp3" to "mp3",
        "opus" to "opus",
        "vorbis" to "ogg",
        "wav" to "wav",
    )

    private val thumbnailEmbeddableExtensions = setOf(
        "mp3",
        "mkv",
        "mka",
        "ogg",
        "opus",
        "flac",
        "m4a",
        "mp4",
        "m4v",
        "mov",
    )

    fun sanitize(command: List<String>): List<String> {
        val sanitized = command.toMutableList()
        val requestedAudioFormat = optionArgument(sanitized, "--audio-format")
            ?.lowercase()
            ?: return sanitized
        val outputExtension = audioFormatOutputExtensions[requestedAudioFormat]
            ?: return sanitized

        if (outputExtension in thumbnailEmbeddableExtensions) return sanitized

        val removedEmbedThumbnail = removeFlag(sanitized, "--embed-thumbnail")
        if (removedEmbedThumbnail &&
            !hasOption(sanitized, "--write-thumbnail") &&
            !hasOption(sanitized, "--write-all-thumbnails")
        ) {
            // --convert-thumbnails is only useful here because --embed-thumbnail
            // implicitly downloaded the thumbnail. If the user explicitly asked
            // for a sidecar thumbnail, keep its conversion option intact.
            removeOptionWithArgument(sanitized, "--convert-thumbnails")
        }

        return sanitized
    }

    private fun optionArgument(command: List<String>, option: String): String? {
        for (index in command.indices.reversed()) {
            val token = command[index]
            if (token.startsWith("$option=")) {
                return token.substringAfter('=', missingDelimiterValue = "")
                    .ifEmpty { null }
            }
            if (token == option) {
                return command.getOrNull(index + 1)
            }
        }
        return null
    }

    private fun hasOption(command: List<String>, option: String): Boolean {
        return command.any { it == option || it.startsWith("$option=") }
    }

    private fun removeFlag(command: MutableList<String>, option: String): Boolean {
        val before = command.size
        command.removeAll { it == option || it.startsWith("$option=") }
        return command.size != before
    }

    private fun removeOptionWithArgument(command: MutableList<String>, option: String) {
        var index = 0
        while (index < command.size) {
            val token = command[index]
            when {
                token.startsWith("$option=") -> command.removeAt(index)
                token == option -> {
                    command.removeAt(index)
                    if (index < command.size && !command[index].startsWith("-")) {
                        command.removeAt(index)
                    }
                }
                else -> index++
            }
        }
    }
}
