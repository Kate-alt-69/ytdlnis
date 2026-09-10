package com.deniscerri.ytdl.core.models

import java.io.File
import java.nio.file.Files
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class YTDLCommandCompatibilityTest {
    @Test
    fun removesThumbnailEmbeddingFromWavDownloads() {
        val command = YTDLCommandCompatibility.sanitize(
            listOf(
                "-x",
                "--audio-format", "wav",
                "--embed-metadata",
                "--embed-thumbnail",
                "--convert-thumbnails", "jpg",
                "https://youtu.be/example",
            ),
        )

        assertTrue(command.containsAll(listOf("--audio-format", "wav", "--embed-metadata")))
        assertFalse(command.contains("--embed-thumbnail"))
        assertFalse(command.contains("--convert-thumbnails"))
    }

    @Test
    fun keepsThumbnailEmbeddingForSupportedAudioContainers() {
        listOf("mp3", "m4a", "opus", "flac", "aac", "alac", "vorbis").forEach { format ->
            val command = YTDLCommandCompatibility.sanitize(
                listOf(
                    "-x",
                    "--audio-format", format,
                    "--embed-thumbnail",
                    "--convert-thumbnails", "jpg",
                ),
            )

            assertTrue("thumbnail embedding should remain for $format", command.contains("--embed-thumbnail"))
            assertTrue("thumbnail conversion should remain for $format", command.contains("--convert-thumbnails"))
        }
    }

    @Test
    fun preservesExplicitSidecarThumbnailForWav() {
        val command = YTDLCommandCompatibility.sanitize(
            listOf(
                "-x",
                "--audio-format=wav",
                "--embed-thumbnail",
                "--write-thumbnail",
                "--convert-thumbnails=jpg",
            ),
        )

        assertFalse(command.contains("--embed-thumbnail"))
        assertTrue(command.contains("--write-thumbnail"))
        assertTrue(command.contains("--convert-thumbnails=jpg"))
    }

    @Test
    fun leavesUnknownAudioFormatsUntouched() {
        val command = listOf(
            "-x",
            "--audio-format", "future-format",
            "--embed-thumbnail",
        )

        assertTrue(YTDLCommandCompatibility.sanitize(command).contains("--embed-thumbnail"))
    }

    @Test
    fun sanitizesQuotedWavConfigWithoutDamagingOtherArguments() {
        val config = """--newline -x --audio-format "wav" -S "acodec:opus,aext:wav" --ppa "ThumbnailsConvertor:-qmin 1 -q:v 1 -vf crop=\"'if(gt(ih,iw),iw,ih)':'if(gt(iw,ih),ih,iw)'\"" --replace-in-metadata "title" "^.*$" "BACK2BACK" --embed-metadata --embed-thumbnail --convert-thumbnails "jpg""""

        val sanitized = YTDLCommandCompatibility.sanitizeConfigText(config)

        assertTrue(sanitized.contains("""--audio-format "wav"""))
        assertTrue(sanitized.contains("""--ppa "ThumbnailsConvertor:-qmin 1 -q:v 1 -vf crop="""))
        assertTrue(sanitized.contains("""--replace-in-metadata "title" "^.*$" "BACK2BACK"""))
        assertTrue(sanitized.contains("--embed-metadata"))
        assertFalse(sanitized.contains("--embed-thumbnail"))
        assertFalse(sanitized.contains("--convert-thumbnails"))
    }

    @Test
    fun preservesExplicitSidecarThumbnailInWavConfig() {
        val config = """-x --audio-format "wav" --embed-thumbnail --write-thumbnail --convert-thumbnails "jpg""""

        val sanitized = YTDLCommandCompatibility.sanitizeConfigText(config)

        assertFalse(sanitized.contains("--embed-thumbnail"))
        assertTrue(sanitized.contains("--write-thumbnail"))
        assertTrue(sanitized.contains("""--convert-thumbnails "jpg"""))
    }

    @Test
    fun sanitizesYtdlnisGeneratedConfigLocationBeforeExecution() {
        val directory = Files.createTempDirectory("ytdlnis-command-").toFile()
        val config = File(
            directory,
            "${System.currentTimeMillis()}${UUID.randomUUID()}.txt",
        )
        val original = """--newline -x --audio-format "wav" --embed-metadata --embed-thumbnail --convert-thumbnails "jpg""""

        try {
            config.writeText(original)

            YTDLCommandCompatibility.sanitize(
                listOf(
                    "--config-locations", config.absolutePath,
                    "https://youtu.be/example",
                ),
            )

            val sanitized = config.readText()
            assertTrue(sanitized.contains("""--audio-format "wav"""))
            assertTrue(sanitized.contains("--embed-metadata"))
            assertFalse(sanitized.contains("--embed-thumbnail"))
            assertFalse(sanitized.contains("--convert-thumbnails"))
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun doesNotRewriteArbitraryUserConfigFiles() {
        val directory = Files.createTempDirectory("ytdlnis-user-config-").toFile()
        val config = File(directory, "custom.conf")
        val original = """-x --audio-format "wav" --embed-thumbnail --convert-thumbnails "jpg""""

        try {
            config.writeText(original)

            YTDLCommandCompatibility.sanitize(
                listOf("--config-locations", config.absolutePath),
            )

            assertEquals(original, config.readText())
        } finally {
            directory.deleteRecursively()
        }
    }
}
