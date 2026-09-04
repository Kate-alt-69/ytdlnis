"""YTDLnis yt-dlp extractor for Instagram Reels audio pages.

Instagram's normal yt-dlp extractor deliberately excludes /reels/audio/<id>
URLs. This extractor resolves the numeric audio asset through Instagram's
clips/music surfaces and exposes the original audio stream as an audio-only
format.
"""

import html
import json
import re

from yt_dlp.extractor.instagram import InstagramBaseIE
from yt_dlp.utils import ExtractorError, determine_ext, float_or_none, url_or_none, urlencode_postdata
from yt_dlp.utils.traversal import traverse_obj


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
        exact = []
        fallback = []
        for item in cls._walk_dicts(payload):
            if not any(item.get(key) for key in (*_AUDIO_URL_KEYS, 'dash_manifest')):
                continue
            fallback.append(item)
            if any(str(item.get(key)) == str(audio_id) for key in _AUDIO_ID_KEYS if item.get(key) is not None):
                exact.append(item)
        return (exact or fallback or [None])[0]

    def _api_headers_for_audio(self, webpage_url):
        headers = {
            **self._api_headers,
            'Referer': webpage_url,
            'X-Requested-With': 'XMLHttpRequest',
        }
        csrf_cookie = self._get_cookies(self._BASE_URL).get('csrftoken')
        if csrf_cookie:
            headers['X-CSRFToken'] = csrf_cookie.value
        return headers

    def _download_audio_metadata(self, webpage_url, audio_id):
        headers = self._api_headers_for_audio(webpage_url)
        common = {
            'audio_cluster_id': audio_id,
            'original_sound_audio_asset_id': audio_id,
        }

        # This is the same app surface Instagram uses for audio aggregation pages.
        payload = self._download_json(
            f'{self._API_BASE_URL}/clips/music/', audio_id,
            note='Downloading Instagram audio metadata',
            errnote='Instagram audio metadata request failed',
            fatal=False,
            headers=headers,
            data=urlencode_postdata(common)) or {}
        audio_info = self._find_audio_info(payload, audio_id)
        if audio_info:
            return audio_info

        # Some accounts/rollouts expose the asset on the streamed pivot endpoint
        # rather than the older clips/music response.
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
        webpage = self._download_webpage(
            webpage_url, audio_id,
            note='Checking Instagram audio webpage',
            errnote='Instagram audio webpage request failed',
            fatal=False,
            impersonate=self._can_impersonate)
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
                    result['dash_manifest'] = dash_manifest.replace('\\n', '\n').replace('\\"', '"').replace('\\/', '/')

            if any(result.get(key) for key in (*_AUDIO_URL_KEYS, 'dash_manifest')):
                result['title'] = self._og_search_title(webpage, default=None)
                return result
        return None

    def _extract_formats(self, audio_info, audio_id):
        formats = []
        seen = set()

        # Prefer the full progressive asset. Only use the web preview when the full
        # asset is not exposed by this Instagram rollout.
        preferred_keys = _AUDIO_URL_KEYS[:-1]
        progressive_found = False
        for key in preferred_keys:
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
                'http_headers': {'Referer': 'https://www.instagram.com/'},
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
                    'http_headers': {'Referer': 'https://www.instagram.com/'},
                })

        dash_manifest = audio_info.get('dash_manifest')
        if isinstance(dash_manifest, str) and dash_manifest.strip():
            mpd_doc = self._parse_xml(dash_manifest, audio_id, fatal=False)
            if mpd_doc is not None:
                for fmt in self._parse_mpd_formats(mpd_doc, mpd_id='dash'):
                    fmt.setdefault('vcodec', 'none')
                    formats.append(fmt)

        return formats

    def _real_extract(self, url):
        audio_id = self._match_id(url)
        clean_url = f'https://www.instagram.com/reels/audio/{audio_id}/'

        audio_info = self._download_audio_metadata(clean_url, audio_id)
        if not audio_info:
            audio_info = self._audio_from_webpage(clean_url, audio_id)
        if not audio_info:
            hint = ' Enable Instagram cookies in YTDLnis and retry.' if not self._is_logged_in else ''
            raise ExtractorError(
                f'Instagram did not expose downloadable media for audio {audio_id}.{hint}',
                expected=True)

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
