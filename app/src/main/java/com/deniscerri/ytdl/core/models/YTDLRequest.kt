package com.deniscerri.ytdl.core.models

import com.deniscerri.ytdl.core.RuntimeManager

class YTDLRequest {
    private val urls: List<String>
    private val options = YTDLOptions()
    private val customCommandList: MutableList<String> = ArrayList()

    constructor(url: String) {
        urls = listOf(url)
    }

    constructor(urls: List<String>) {
        this.urls = urls
    }

    fun addOption(option: String, argument: String): YTDLRequest {
        options.addOption(option, argument)
        return this
    }

    fun addOption(option: String, argument: Number): YTDLRequest {
        options.addOption(option, argument)
        return this
    }

    fun addOption(option: String): YTDLRequest {
        options.addOption(option)
        return this
    }

    fun addCommands(commands: List<String>): YTDLRequest {
        customCommandList.addAll(commands)
        return this
    }

    fun getOption(option: String): String? {
        return options.getArgument(option)
    }

    fun getArguments(option: String): List<String?>? {
        return options.getArguments(option)
    }

    fun hasOption(option: String): Boolean {
        return options.hasOption(option)
    }

    /** Extends an existing namespaced downloader argument without duplicating it. */
    fun appendToOptionArgument(option: String, argumentPrefix: String, suffix: String): Boolean {
        return options.appendToArgument(option, argumentPrefix, suffix)
    }

    fun buildCommand(): List<String> {
        // YTDLnis runs yt-dlp as a Python zipapp on Android, so yt-dlp's normal
        // executable-location plugin discovery does not reliably point at the
        // portable runtime directory. Explicitly add our plugin package root to
        // every request once installation has created it. Keep any user-supplied
        // plugin directories alongside it, and never pass a missing directory to
        // yt-dlp because explicit invalid plugin paths are fatal.
        val socialPluginDir = RuntimeManager.ytdlpPath
            ?.parentFile
            ?.resolve("yt-dlp-plugins")
        if (socialPluginDir?.isDirectory == true
            && getArguments("--plugin-dirs")?.none { it == socialPluginDir.absolutePath } != false
        ) {
            options.addOption("--plugin-dirs", socialPluginDir.absolutePath)
        }

        val commandList: MutableList<String> = ArrayList()
        commandList.addAll(options.buildOptions())
        commandList.addAll(customCommandList)
        commandList.addAll(urls)
        return commandList
    }
}
