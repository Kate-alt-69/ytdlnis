package com.deniscerri.ytdl.core.models

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
}
