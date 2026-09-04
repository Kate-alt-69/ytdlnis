"""yt-dlp extractor plugin for Threads (threads.com / threads.net).

Vendored by YTDLnis from tribixbite/yt-dlp-threads (Unlicense/public domain),
revision c4c44141cb10715f94296a808f5d89a0d24dfe94.

Threads serves anonymous browser clients a JavaScript login wall with no
media. Meta does server-render the full post for link-preview crawlers, so the
extractor fetches with a crawler User-Agent and selects the requested post by
its shortcode. Image-only posts are intentionally unsupported by YTDLnis.
"""

import base64
import json
import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    int_or_none,
    parse_qs,
    str_or_none,
    url_or_none,
)
from yt_dlp.utils.traversal import traverse_obj

_GOOGLEBOT_UA = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
_MEDIA_KEYS = {'video_versions', 'video_dash_manifest', 'image_versions2', 'carousel_media'}
_MEDIA_TYPE_IMAGE = 1
_MEDIA_TYPE_CAROUSEL = 8


class ThreadsIE(InfoExtractor):
    IE_NAME = 'threads'
    _VALID_URL = r'''(?x)
        https?://(?:www\.)?threads\.(?:net|com)/
        (?:
            (?:@(?P<user>[^/?#]+)/post|t)/(?P<id>[\w-]+)
            |share/(?P<share>[\w-]+)
        )'''
    _TESTS = [{
        'url': 'https://www.threads.com/@kfury/post/DaGcWDwj8tW',
        'info_dict': {
            'id': 'DaGcWDwj8tW',
            'ext': 'mp4',
            'title': str,
            'uploader_id': 'kfury',
            'uploader_url': 'https://www.threads.com/@kfury',
            'timestamp': int,
            'upload_date': str,
        },
        'params': {'skip_download': True},
    }, {
        'url': 'https://www.threads.com/share/_srJIVx6G/',
        'only_matching': True,
    }, {
        'url': 'https://www.threads.net/@zuck/post/C8Xw3vLxabc',
        'only_matching': True,
    }, {
        'url': 'https://www.threads.com/t/C8Xw3vLxabc',
        'only_matching': True,
    }]

    def _collect_posts(self, obj, out):
        if isinstance(obj, dict):
            if obj.get('code') and (obj.keys() & _MEDIA_KEYS):
                out.append(obj)
            for value in obj.values():
                self._collect_posts(value, out)
        elif isinstance(obj, list):
            for value in obj:
                self._collect_posts(value, out)

    def _extract_posts(self, webpage, video_id):
        posts = []
        for block in re.findall(
                r'<script type="application/json"[^>]*>(.*?)</script>', webpage, re.S):
            data = self._parse_json(block, video_id, fatal=False, errnote=False)
            if data is not None:
                self._collect_posts(data, posts)
        return posts

    @staticmethod
    def _efg_info(url):
        efg = traverse_obj(parse_qs(url), ('efg', 0, {str}))
        if not efg:
            return {}
        try:
            return json.loads(base64.urlsafe_b64decode(efg + '=' * (-len(efg) % 4)))
        except (ValueError, TypeError):
            return {}

    def _formats_from_media(self, media, video_id):
        formats = []

        manifest = traverse_obj(media, ('video_dash_manifest', {str}))
        if manifest:
            mpd_doc = self._parse_xml(manifest, video_id, fatal=False)
            if mpd_doc is not None:
                formats.extend(self._parse_mpd_formats(mpd_doc, mpd_id='dash'))

        fallback_w = int_or_none(media.get('original_width'))
        fallback_h = int_or_none(media.get('original_height'))
        acodec = 'none' if media.get('has_audio') is False else None
        seen = set()
        for version in media.get('video_versions') or []:
            media_url = url_or_none(version.get('url'))
            if not media_url:
                continue
            path = media_url.split('?')[0]
            if path in seen:
                continue
            seen.add(path)
            fmt = {
                'url': media_url,
                'format_id': str_or_none(version.get('type')) or f'http-{len(formats)}',
                'ext': 'mp4',
                'width': int_or_none(version.get('width')) or fallback_w,
                'height': int_or_none(version.get('height')) or fallback_h,
                'http_headers': {'Referer': 'https://www.threads.com/'},
            }
            if acodec:
                fmt['acodec'] = acodec
            formats.append(fmt)
        return formats

    def _media_entry(self, media, item_id):
        formats = self._formats_from_media(media, item_id)
        if not formats:
            return None
        duration = None
        for fmt in formats:
            duration = int_or_none(self._efg_info(fmt['url']).get('duration_s'))
            if duration:
                break
        return {
            'id': item_id,
            'formats': formats,
            'duration': duration,
            'thumbnails': traverse_obj(media, (
                'image_versions2', 'candidates', lambda _, v: url_or_none(v['url']), {
                    'url': 'url',
                    'width': ('width', {int_or_none}),
                    'height': ('height', {int_or_none}),
                })),
        }

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        matched_id = mobj.group('id') or mobj.group('share')

        webpage = self._download_webpage(
            url, matched_id, note='Downloading Threads post webpage',
            headers={'User-Agent': _GOOGLEBOT_UA})

        target_code = mobj.group('id')
        if not target_code:
            target_code = self._search_regex(
                r'/post/([\w-]+)',
                self._og_search_property('url', webpage, default='') or '',
                'post id', default=None)

        posts = self._extract_posts(webpage, matched_id)
        if target_code:
            post = next((p for p in posts if p.get('code') == target_code), None)
            if post is None:
                raise ExtractorError(
                    f'Post "{target_code}" was not found in the page data. It may be '
                    'deleted, private, login-gated, or Threads changed its layout.',
                    expected=True)
        else:
            post = next((p for p in posts if p.get('video_versions')
                         or p.get('video_dash_manifest')), None)
            if post is None:
                raise ExtractorError('No video post found on this page.', expected=True)
            self.report_warning(
                'Could not determine which post this link points to; using the first '
                'video on the page. Pass the canonical @user/post/<id> URL to be sure.')

        video_id = post.get('code') or target_code or matched_id
        user = post.get('user') or {}
        caption = traverse_obj(post, ('caption', 'text')) or post.get('accessibility_caption')
        uploader_id = user.get('username') or mobj.group('user')
        common = {
            'description': caption,
            'uploader': user.get('full_name') or uploader_id,
            'uploader_id': uploader_id,
            'uploader_url': f'https://www.threads.com/@{uploader_id}' if uploader_id else None,
            'timestamp': int_or_none(post.get('taken_at')),
            'like_count': int_or_none(post.get('like_count')),
            'webpage_url': url_or_none(post.get('canonical_url')) or url,
        }
        title = (caption or '').split('\n')[0][:72] or (
            f'Threads video by {uploader_id}' if uploader_id else f'Threads video {video_id}')

        carousel = post.get('carousel_media')
        if isinstance(carousel, list) and carousel:
            entries = []
            for idx, item in enumerate(carousel):
                entry = self._media_entry(item, f'{video_id}_{idx + 1}')
                if entry:
                    entry.update(common)
                    entry['title'] = f'{title} (part {idx + 1})'
                    entries.append(entry)
            if not entries:
                raise ExtractorError(
                    'This carousel post contains no videos (images are not supported)',
                    expected=True)
            if len(entries) == 1:
                return entries[0]
            return self.playlist_result(
                entries, playlist_id=video_id, playlist_title=title,
                playlist_description=caption, multi_video=True)

        entry = self._media_entry(post, video_id)
        if entry is None:
            kind = ('an image post' if post.get('media_type') == _MEDIA_TYPE_IMAGE
                    else 'a carousel' if post.get('media_type') == _MEDIA_TYPE_CAROUSEL
                    else 'text-only or unsupported')
            raise ExtractorError(
                f'Post "{video_id}" has no downloadable video ({kind})', expected=True)
        entry.update(common)
        entry['title'] = title
        return entry
