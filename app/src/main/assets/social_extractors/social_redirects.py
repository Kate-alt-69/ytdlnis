"""Small URL resolvers for social video links that fall through yt-dlp.

These extractors intentionally do not replace the mature built-in site
extractors. They normalize unsupported share/story URL shapes and hand the
canonical media URL back to yt-dlp whenever possible.
"""

import html
import json
import re
import urllib.parse

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.extractor.snapchat import SnapchatSpotlightIE
from yt_dlp.utils import ExtractorError, url_or_none


_TRACKING_QUERY_KEYS = {
    'fbclid', 'igsh', 'igshid', 'mibextid', 'rdid', 'share_id', 'share_url',
    'invite_id', 'locale', 'sid', 'utm_campaign', 'utm_content', 'utm_medium',
    'utm_source', 'utm_term',
}


def _clean_tracking_url(url):
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [
        (key, value) for key, value in query
        if key.lower() not in _TRACKING_QUERY_KEYS and not key.lower().startswith('utm_')
    ]
    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urllib.parse.urlencode(query),
        '',
    ))


class _RedirectResolverIE(InfoExtractor):
    def _resolve_redirect(self, url, display_id, note):
        webpage, urlh = self._download_webpage_handle(
            url, display_id, note=note,
            errnote='Could not resolve shared social URL')
        final_url = urlh.url

        # Some Meta short links return 200 with the canonical target in og:url
        # instead of issuing another HTTP redirect.
        canonical = self._og_search_property('url', webpage, default=None)
        if url_or_none(canonical):
            final_url = canonical
        return _clean_tracking_url(final_url)


class InstagramShareIE(_RedirectResolverIE):
    IE_NAME = 'instagram:share'
    _VALID_URL = r'https?://(?:www\.)?instagram\.com/share/(?P<id>[^?#]+)'
    _TESTS = [{
        'url': 'https://www.instagram.com/share/reel/BAExampleShareCode/',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        display_id = self._match_id(url).strip('/')
        target = self._resolve_redirect(url, display_id, 'Resolving Instagram share URL')
        if '/share/' in urllib.parse.urlsplit(target).path:
            raise ExtractorError('Instagram did not resolve this share link to a media URL', expected=True)
        return self.url_result(target)


class FacebookShareIE(_RedirectResolverIE):
    IE_NAME = 'facebook:share'
    _VALID_URL = r'''(?x)https?://(?:www\.)?(?:
        facebook\.com/share/(?:r|v|p)/(?P<fbid>[^/?#]+)
        |fb\.watch/(?P<watchid>[^/?#]+)
    )'''
    _TESTS = [{
        'url': 'https://www.facebook.com/share/r/1HNwyf2jVo/',
        'only_matching': True,
    }, {
        'url': 'https://www.facebook.com/share/v/1BNt6NU62h/',
        'only_matching': True,
    }, {
        'url': 'https://fb.watch/example/',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        display_id = mobj.group('fbid') or mobj.group('watchid')
        target = self._resolve_redirect(url, display_id, 'Resolving Facebook share URL')
        parsed = urllib.parse.urlsplit(target)
        if '/share/' in parsed.path or parsed.netloc.endswith('fb.watch'):
            raise ExtractorError('Facebook did not resolve this share link to a video URL', expected=True)
        return self.url_result(target)


class FacebookStoryIE(InfoExtractor):
    """Best-effort public Facebook Story video extraction.

    Facebook story URLs are not accepted by the built-in Facebook extractor.
    Public story pages can still expose progressive delivery URLs in Relay JSON
    or OpenGraph metadata. Login-gated/expired stories remain unavailable unless
    Facebook returns those fields with the user's cookies.
    """

    IE_NAME = 'facebook:story'
    _VALID_URL = r'https?://(?:www\.|m\.)?facebook\.com/stories/(?P<actor>[^/?#]+)/(?P<id>[^/?#]+)'
    _TESTS = [{
        'url': 'https://www.facebook.com/stories/123456789/UzpfSVNDOjEyMzQ1Njc4OTA=/?view_single=1',
        'only_matching': True,
    }]

    @staticmethod
    def _decode_json_url(raw):
        if not raw:
            return None
        try:
            value = json.loads(f'"{raw}"')
        except (TypeError, ValueError, json.JSONDecodeError):
            value = raw.replace('\\u0026', '&').replace('\\/', '/')
        return url_or_none(html.unescape(value))

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        actor, story_id = mobj.group('actor', 'id')
        webpage = self._download_webpage(
            url, story_id, note='Downloading Facebook Story webpage',
            headers={'User-Agent': 'facebookexternalhit/1.1'})

        formats = []
        seen = set()
        field_names = (
            ('browser_native_hd_url', 'hd'),
            ('playable_url_quality_hd', 'hd'),
            ('browser_native_sd_url', 'sd'),
            ('playable_url', 'sd'),
        )
        for key, format_id in field_names:
            for raw in re.findall(
                    rf'"{key}"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', webpage):
                media_url = self._decode_json_url(raw)
                if not media_url or media_url in seen:
                    continue
                seen.add(media_url)
                formats.append({
                    'url': media_url,
                    'format_id': format_id,
                    'ext': 'mp4',
                    'http_headers': {'User-Agent': 'facebookexternalhit/1.1'},
                })

        if not formats:
            og_video = self._html_search_meta(
                ('og:video', 'og:video:url', 'og:video:secure_url'),
                webpage, 'video URL', default=None)
            og_video = url_or_none(og_video)
            if og_video:
                formats.append({
                    'url': og_video,
                    'format_id': 'http',
                    'ext': 'mp4',
                    'http_headers': {'User-Agent': 'facebookexternalhit/1.1'},
                })

        if not formats:
            raise ExtractorError(
                'This Facebook Story did not expose a downloadable video. It may be '
                'expired, private, image-only, or require Facebook login cookies.',
                expected=True)

        title = (
            self._og_search_title(webpage, default=None)
            or self._html_search_meta('twitter:title', webpage, default=None)
            or f'Facebook Story by {actor}')
        return {
            'id': story_id,
            'title': title,
            'description': self._og_search_description(webpage, default=None),
            'thumbnail': self._og_search_thumbnail(webpage, default=None),
            'uploader_id': actor,
            'formats': formats,
            'webpage_url': url,
        }


class SnapchatAuthorSpotlightIE(InfoExtractor):
    IE_NAME = 'snapchat:author-spotlight'
    _VALID_URL = r'https?://(?:www\.)?snapchat\.com/@(?P<user>[^/?#]+)/spotlight/(?P<id>[^/?#]+)'
    _TESTS = [{
        'url': 'https://www.snapchat.com/@creator/spotlight/W7_EDlXWTBiXAEExample',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        video_id = self._match_valid_url(url).group('id')
        return self.url_result(
            f'https://www.snapchat.com/spotlight/{video_id}',
            ie=SnapchatSpotlightIE.ie_key(), video_id=video_id)


class SnapchatShareIE(_RedirectResolverIE):
    IE_NAME = 'snapchat:share'
    _VALID_URL = r'https?://(?:www\.)?snapchat\.com/t/(?P<id>[A-Za-z0-9]+)'
    _TESTS = [{
        'url': 'https://snapchat.com/t/IaRQGAOQ',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        share_id = self._match_id(url)
        target = self._resolve_redirect(url, share_id, 'Resolving Snapchat share URL')

        author_spotlight = re.match(
            r'https?://(?:www\.)?snapchat\.com/@[^/?#]+/spotlight/(?P<id>[^/?#]+)',
            target)
        if author_spotlight:
            video_id = author_spotlight.group('id')
            return self.url_result(
                f'https://www.snapchat.com/spotlight/{video_id}',
                ie=SnapchatSpotlightIE.ie_key(), video_id=video_id)

        if '/t/' in urllib.parse.urlsplit(target).path:
            raise ExtractorError('Snapchat did not resolve this share link to media', expected=True)
        return self.url_result(target)
