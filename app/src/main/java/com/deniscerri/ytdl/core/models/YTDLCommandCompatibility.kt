package com.deniscerri.ytdl.core.models

import java.io.File

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

    private val generatedConfigName = Regex(
        """^\d{10,}[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.txt$""",
    )
    private val configAudioFormat = Regex(
        """(?<!\S)--audio-format(?:=|\s+)(?:"([^"]+)"|'([^']+)'|([^\s]+))""",
    )
    private val configEmbedThumbnail = Regex(
        """(?<!\S)--embed-thumbnail(?=\s|$)""",
    )
    private val configWriteThumbnail = Regex(
        """(?<!\S)--(?:write-thumbnail|write-all-thumbnails)(?=\s|$)""",
    )
    private val configConvertThumbnails = Regex(
        """(?<!\S)--convert-thumbnails(?:=(?:"[^"]*"|'[^']*'|[^\s]+)|\s+(?:"[^"]*"|'[^']*'|(?!-)[^\s]+))?""",
    )

    fun sanitize(command: List<String>): List<String> {
        val sanitized = command.toMutableList()

        // Download requests keep most yt-dlp arguments in a generated config
        // file. Sanitize those files before checking the outer command, otherwise
        // combinations such as WAV + --embed-thumbnail remain invisible here.
        sanitizeGeneratedConfigFiles(sanitized)

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

    /**
     * Sanitizes a command string exactly as YTDLnis writes it into its generated
     * --config-locations files. Quoted metadata and postprocessor arguments are
     * deliberately left untouched; only the incompatible thumbnail options are
     * removed.
     */
    internal fun sanitizeConfigText(config: String): String {
        val audioFormatMatch = configAudioFormat.findAll(config).lastOrNull()
            ?: return config
        val requestedAudioFormat = audioFormatMatch.groupValues
            .drop(1)
            .firstOrNull { it.isNotEmpty() }
            ?.lowercase()
            ?: return config
        val outputExtension = audioFormatOutputExtensions[requestedAudioFormat]
            ?: return config

        if (outputExtension in thumbnailEmbeddableExtensions ||
            !configEmbedThumbnail.containsMatchIn(config)
        ) {
            return config
        }

        var sanitized = configEmbedThumbnail.replace(config, "")
        if (!configWriteThumbnail.containsMatchIn(sanitized)) {
            sanitized = configConvertThumbnails.replace(sanitized, "")
        }
        return sanitized
    }

    private fun sanitizeGeneratedConfigFiles(command: List<String>) {
        optionArguments(command, "--config-locations").forEach { path ->
            val file = File(path)
            // Never rewrite an arbitrary user-owned yt-dlp config. YTDLnis uses
            // <timestamp><UUID>.txt for the ephemeral configs it owns.
            if (!file.isFile || !generatedConfigName.matches(file.name)) return@forEach

            val original = runCatching { file.readText() }.getOrNull() ?: return@forEach
            val sanitized = sanitizeConfigText(original)
            if (sanitized != original) {
                runCatching { file.writeText(sanitized) }
            }
        }
    }

    private fun optionArguments(command: List<String>, option: String): List<String> {
        val arguments = mutableListOf<String>()
        command.forEachIndexed { index, token ->
            when {
                token.startsWith("$option=") -> {
                    token.substringAfter('=', missingDelimiterValue = "")
                        .ifEmpty { null }
                        ?.let(arguments::add)
                }
                token == option -> {
                    command.getOrNull(index + 1)
                        ?.takeUnless { it.startsWith("-") }
                        ?.let(arguments::add)
                }
            }
        }
        return arguments
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
