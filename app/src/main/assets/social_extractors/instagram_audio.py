"""YTDLnis yt-dlp extractor for Instagram Reels audio pages.

Instagram's normal yt-dlp extractor deliberately excludes /reels/audio/<id>
URLs. This extractor resolves the numeric audio asset through Instagram's
clips/music surfaces and exposes the original audio stream as an audio-only
format.

Keep this plugin compatible with the yt-dlp version bundled by YTDLnis. In
particular, yt-dlp 2025.11.12 exposes InstagramBaseIE._API_BASE_URL and
_api_headers, but not newer helpers such as _BASE_URL, _is_logged_in, or
_can_impersonate.
"""

import html
import json
import re

from yt_dlp.extractor.instagram import InstagramBaseIE
from yt_dlp.utils import ExtractorError, determine_ext, float_or_none, url_or_none, urlencode_postdata
from yt_dlp.utils.traversal import traverse_obj


_WEB_BASE_URL = 'https://www.instagram.com/'
_AUDIO_URL_KEYS = (
    'progressive_download_url',
    'fast_start_progressive_download_url',
    'reactive_audio_download_url',
    'web_30s_preview_download_url',
)
_AUDIO_ID_KEYS = (
    'audio_asset_id',
    'audio_cluster_id',
    'music_canonical_id',
    'id',
)


class InstagramAudioIE(InstagramBaseIE):
    IE_NAME = 'instagram:audio'
    _VALID_URL = r'https?://(?:www\.)?instagram\.com/reels/audio/(?P<id>\d+)(?:[/?#]|$)'
    _TESTS = [{
        'url': 'https://www.instagram.com/reels/audio/1388369548211802/',
        'only_matching': True,
    }, {
        'url': 'https://www.instagram.com/reels/audio/1388369548211802?igsi=test',
        'only_matching': True,
    }, {
        'url': 'https://www.instagram.com/reels/audio/1514279692102050?igsi=test',
        'only_matching': True,
    }]

    @staticmethod
    def _walk_dicts(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from InstagramAudioIE._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from InstagramAudioIE._walk_dicts(child)

    @classmethod
    def _find_audio_info(cls, payload, audio_id):
        """Find the audio object without accidentally selecting a recommended sound."""
        exact = []
        fallback = []
        for item in cls._walk_dicts(payload):
            if not any(item.get(key) for key in (*_AUDIO_URL_KEYS, 'dash_manifest')):
                continue
            fallback.append(item)
            if any(
                    str(item.get(key)) == str(audio_id)
                    for key in _AUDIO_ID_KEYS if item.get(key) is not None):
                exact.append(item)
        return (exact or fallback or [None])[0]

    def _instagram_cookies(self):
        # Cookies supplied through YTDLnis/yt-dlp's normal --cookies option are
        # already loaded into yt-dlp's cookie jar. Do not maintain a second login
        # store in the plugin.
        return self._get_cookies(_WEB_BASE_URL)

    def _has_instagram_session(self):
        return bool(self._instagram_cookies().get('sessionid'))

    def _api_headers_for_audio(self, webpage_url):
        headers = {
            **self._api_headers,
            'Referer': webpage_url,
            'X-Requested-With': 'XMLHttpRequest',
        }
        csrf_cookie = self._instagram_cookies().get('csrftoken')
        if csrf_cookie:
            headers['X-CSRFToken'] = csrf_cookie.value
        return headers

    def _download_audio_metadata(self, webpage_url, audio_id):
        headers = self._api_headers_for_audio(webpage_url)

        # This mirrors Instagram's track-info request. It is also the request
        # shape used by maintained Instagram private-API clients.
        payload = self._download_json(
            f'{self._API_BASE_URL}/clips/music/', audio_id,
            note='Downloading Instagram audio metadata',
            errnote='Instagram audio metadata request failed',
            fatal=False,
            headers=headers,
            data=urlencode_postdata({
                'audio_cluster_id': audio_id,
                'original_sound_audio_asset_id': audio_id,
            })) or {}
        audio_info = self._find_audio_info(payload, audio_id)
        if audio_info:
            return audio_info

        # Newer Instagram clients can render the Audio page through the streamed
        # clips-pivot endpoint. Keep it as a second API path because deployments
        # differ between accounts/regions.
        music_page = {
            'tab_type': 'clips',
            'audio_asset_id': audio_id,
            'audio_cluster_id': audio_id,
        }
        payload = self._download_json(
            f'{self._API_BASE_URL}/clips/stream_clips_pivot_page/', audio_id,
            note='Downloading Instagram audio pivot metadata',
            errnote='Instagram audio pivot request failed',
            fatal=False,
            headers=headers,
            data=urlencode_postdata({
                'pivot_page_type': 'audio',
                'music_page': json.dumps(music_page, separators=(',', ':')),
            })) or {}
        return self._find_audio_info(payload, audio_id)

    @staticmethod
    def _decode_embedded_url(value):
        if not value:
            return None
        try:
            value = json.loads(f'"{value}"')
        except (TypeError, ValueError, json.JSONDecodeError):
            value = value.replace('\\u0026', '&').replace('\\/', '/')
        return url_or_none(html.unescape(value))

    def _audio_from_webpage(self, webpage_url, audio_id):
        # Do not pass newer yt-dlp-only `impersonate=` helpers here. YTDLnis
        # currently bundles yt-dlp 2025.11.12 and its normal downloader headers +
        # cookie jar are sufficient for the authenticated webpage path.
        webpage = self._download_webpage(
            webpage_url, audio_id,
            note='Checking Instagram audio webpage',
            errnote='Instagram audio webpage request failed',
            fatal=False)
        if not webpage:
            return None

        # Prefer JSON close to the requested asset id. Reels audio pages can carry
        # recommendation data for other sounds too, so a page-wide first match can
        # silently select the wrong audio.
        windows = []
        for match in re.finditer(re.escape(str(audio_id)), webpage):
            windows.append(webpage[max(0, match.start() - 12_000):match.end() + 24_000])
        windows.append(webpage)

        for window in windows:
            result = {'id': audio_id}
            for key in _AUDIO_URL_KEYS:
                raw_url = self._search_regex(
                    rf'"{re.escape(key)}"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
                    window, key, default=None)
                media_url = self._decode_embedded_url(raw_url)
                if media_url:
                    result[key] = media_url

            dash_manifest = self._search_regex(
                r'"dash_manifest"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"',
                window, 'DASH manifest', default=None)
            if dash_manifest:
                try:
                    result['dash_manifest'] = json.loads(f'"{dash_manifest}"')
                except (TypeError, ValueError, json.JSONDecodeError):
                    result['dash_manifest'] = (
                        dash_manifest.replace('\\n', '\n')
                        .replace('\\"', '"')
                        .replace('\\/', '/'))

            if any(result.get(key) for key in (*_AUDIO_URL_KEYS, 'dash_manifest')):
                result['title'] = self._og_search_title(webpage, default=None)
                return result
        return None

    def _extract_formats(self, audio_info, audio_id):
        formats = []
        seen = set()

        # Prefer a full progressive asset. The 30-second web preview is a fallback,
        # not an equivalent replacement for the underlying track asset.
        progressive_found = False
        for key in _AUDIO_URL_KEYS[:-1]:
            media_url = url_or_none(audio_info.get(key))
            if not media_url or media_url in seen:
                continue
            seen.add(media_url)
            progressive_found = True
            ext = determine_ext(media_url, default_ext='m4a')
            if ext == 'mp4':
                ext = 'm4a'
            formats.append({
                'url': media_url,
                'format_id': key.removesuffix('_download_url'),
                'ext': ext,
                'vcodec': 'none',
                'http_headers': {'Referer': _WEB_BASE_URL},
            })

        if not progressive_found:
            preview_url = url_or_none(audio_info.get('web_30s_preview_download_url'))
            if preview_url:
                formats.append({
                    'url': preview_url,
                    'format_id': 'preview-30s',
                    'format_note': '30 second preview',
                    'ext': 'm4a',
                    'vcodec': 'none',
                    'preference': -20,
                    'http_headers': {'Referer': _WEB_BASE_URL},
                })

        dash_manifest = audio_info.get('dash_manifest')
        if isinstance(dash_manifest, str) and dash_manifest.strip():
            mpd_doc = self._parse_xml(dash_manifest, audio_id, fatal=False)
            if mpd_doc is not None:
                for fmt in self._parse_mpd_formats(mpd_doc, mpd_id='dash'):
                    # This extractor is deliberately audio-only. Instagram audio
                    # manifests should already contain audio Representations, but
                    # keep yt-dlp's format selection from treating them as video.
                    fmt.setdefault('vcodec', 'none')
                    formats.append(fmt)

        return formats

    def _real_extract(self, url):
        audio_id = self._match_id(url)
        clean_url = f'{_WEB_BASE_URL}reels/audio/{audio_id}/'

        audio_info = self._download_audio_metadata(clean_url, audio_id)
        if not audio_info:
            audio_info = self._audio_from_webpage(clean_url, audio_id)
        if not audio_info:
            if self._has_instagram_session():
                message = (
                    f'Instagram did not expose downloadable media for audio {audio_id}. '
                    'The Instagram cookie session may be expired, the audio may be unavailable, '
                    'or this account is not allowed to access the asset.')
            else:
                message = (
                    f'Instagram did not expose downloadable media for audio {audio_id}. '
                    'This audio page may require login; add or enable Instagram cookies in '
                    'YTDLnis and retry.')
            raise ExtractorError(message, expected=True)

        formats = self._extract_formats(audio_info, audio_id)
        if not formats:
            raise ExtractorError(
                f'Instagram returned metadata for audio {audio_id}, but no downloadable audio URL.',
                expected=True)

        artist = (
            audio_info.get('display_artist')
            or traverse_obj(audio_info, ('ig_artist', 'full_name', {str}))
            or traverse_obj(audio_info, ('ig_artist', 'username', {str})))
        title = (
            audio_info.get('title')
            or audio_info.get('original_audio_title')
            or audio_info.get('sanitized_title')
            or f'Instagram audio {audio_id}')
        thumbnail = traverse_obj(audio_info, (
            ('cover_artwork_thumbnail_uri', 'cover_artwork_uri'), {url_or_none}, any))
        if not thumbnail:
            thumbnail = traverse_obj(audio_info, ('ig_artist', 'profile_pic_url', {url_or_none}))

        return {
            'id': audio_id,
            'title': title,
            'artist': artist,
            'uploader': artist,
            'duration': float_or_none(audio_info.get('duration_in_ms'), scale=1000),
            'thumbnail': thumbnail,
            'formats': formats,
            'webpage_url': clean_url,
        }
