"""
Sopel GitHub Plugin

Copyright 2015 Max Gurela
Copyright 2019 dgw

 _______ __ __   __           __
|     __|__|  |_|  |--.--.--.|  |--.
|    |  |  |   _|     |  |  ||  _  |
|_______|__|____|__|__|_____||_____|

"""

from __future__ import annotations

import base64
from collections import deque
from collections.abc import Mapping
import datetime
import json
import operator
import re
import requests
import sys

from sopel import plugin, tools
from sopel.formatting import bold, color, monospace
from sopel.tools.time import get_timezone, format_time, seconds_to_human
from sopel.config.types import BooleanAttribute, StaticSection, ValidatedAttribute

from . import formatting
from .formatting import emojize
from .webhook import setup_webhook, shutdown_webhook


if sys.version_info.major < 3:
    from urllib import urlencode
    from urllib2 import HTTPError
else:
    from urllib.parse import urlencode
    from urllib.error import HTTPError


'''
 _______           __         __
|   |   |.-----.--|  |.--.--.|  |.-----.
|       ||  _  |  _  ||  |  ||  ||  -__|
|__|_|__||_____|_____||_____||__||_____|

'''

# GitHub enforces alphanumeric usernames, and allows only one punctuation character: hyphen ('-')
# Regex copied and slightly modified to meet our needs from CC0 source:
# https://github.com/shinnn/github-username-regex/blob/0794566cc10e8c5a0e562823f8f8e99fa044e5f4/module.js#L1
githubUsername = (
    r'[A-Za-z\d](?:[A-Za-z\d]|-(?=[A-Za-z\d])){0,38}'
)
githubSpecialPaths = (
    r'(?!(?:collections|events|sponsors|topics|trending)/)'  # exclude special sections
)
# GitHub additionally allows dots ('.') in repo names, as well as hyphens
# not copied from anywhere, but handy to simply reuse
githubRepoSlug = r'[A-Za-z0-9\.\-_]+'
# lots of regex and other globals to make this stuff work
baseURL = (
    r'https?://(?:www\.)?github\.com/(?P<user>{username})/(?P<repo>{repo})'.format(
        username=(githubSpecialPaths + githubUsername),
        repo=githubRepoSlug
    )
)
repoURL = baseURL + r'/?(?:#.*|(?!\S))'
issueURL = baseURL + r'/(?:issues|pull)/(?P<num>[\d]+)(?:#issuecomment-(?P<eventID>[\d]+))?'
commitURL = baseURL + r'/(?:commit)/(?P<commit>[A-z0-9\-]+)'
contentURL = baseURL + r'/(?:blob|raw)/(?P<ref>[^/\s]+)/(?P<path>[^#\s]+)(?:#L(?P<start>\d+)(?:-L(?P<end>\d+))?)?'


class GitHubSection(StaticSection):
    client_id = ValidatedAttribute('client_id', default=None)
    client_secret = ValidatedAttribute('client_secret', default=None)
    webhook = BooleanAttribute('webhook', default=False)
    webhook_host = ValidatedAttribute('webhook_host', default='0.0.0.0')
    webhook_port = ValidatedAttribute('webhook_port', default='3333')
    external_url = ValidatedAttribute('external_url', default='http://your_ip_or_domain_here:3333')
    shortest_bare_number = ValidatedAttribute('shortest_bare_number', int, default=2)


def configure(config):
    config.define_section('github', GitHubSection, validate=False)
    config.github.configure_setting('client_id', 'GitHub API Client ID')
    config.github.configure_setting('client_secret', 'GitHub API Client Secret')
    config.github.configure_setting('webhook', 'Enable webhook listener functionality')
    if config.github.webhook:
        config.github.configure_setting('webhook_host', 'Listen IP for incoming webhooks (0.0.0.0 for all IPs)')
        config.github.configure_setting('webhook_port', 'Listen port for incoming webhooks')
        config.github.configure_setting('external_url', 'Callback URL for webhook activation, should be your externally facing domain or IP. You must include the port unless you are reverse proxying.')


def setup(sopel):
    sopel.config.define_section('github', GitHubSection)

    if sopel.config.github.webhook:
        setup_webhook(sopel)


def shutdown(sopel):
    shutdown_webhook(sopel)


'''
 _______ ______ _____        ______                    __
|   |   |   __ |     |_     |   __ |.---.-.----.-----.|__|.-----.-----.
|   |   |      <       |    |    __||  _  |   _|__ --||  ||     |  _  |
|_______|___|__|_______|    |___|   |___._|__| |_____||__||__|__|___  |
                                                                |_____|
'''


def fetch_api_endpoint(bot, url):
    # GitHub deprecated passing authentication via query parameters in November
    # 2019. Passing OAuth client credentials as user/password instead is the
    # supported replacement:
    # https://developer.github.com/changes/2020-02-10-deprecating-auth-through-query-param/
    auth = None
    if bot.config.github.client_id and bot.config.github.client_secret:
        auth = (bot.config.github.client_id, bot.config.github.client_secret)
    return requests.get(url, headers={'X-GitHub-Api-Version': '2022-11-28'}, auth=auth).text


@plugin.find(
    r'(?<![\w\/\.])(?:\b(?:(?P<user>{match_user})\/)?(?P<repo>{match_repo}))?(?<![\/\.])#(?P<num>\d+)\b'
    .format(match_user=githubUsername, match_repo=githubRepoSlug)
)
@plugin.require_chanmsg
def issue_reference(bot, trigger):
    """
    Separate function to work around Sopel not loading rules/commands for @url callables.
    """
    issue_info(bot, trigger, suppress_errors=True)


@plugin.url(issueURL)
def issue_info(bot, trigger, match=None, suppress_errors=False):
    user = trigger.group('user')
    repo = trigger.group('repo')
    num = trigger.group('num')
    comment_id = None

    if match:  # Link triggered
        try:
            comment_id = match.group('eventID')
        except IndexError:
            # meh
            pass
        if comment_id:
            URL = 'https://api.github.com/repos/%s/%s/issues/comments/%s' % (user, repo, comment_id)
        else:
            URL = 'https://api.github.com/repos/%s/%s/issues/%s' % (user, repo, num)
    else:  # Issue/PR number triggered
        channel_repo = bot.db.get_channel_value('github_issue_repo', trigger.sender)

        if not all((user, repo)) and not channel_repo:
            # If at least the user slug is missing, and there's no repo linked to the channel,
            # it's impossible to fill in the blank(s).
            return plugin.NOLIMIT

        # We do have a channel repo, but bare #numbers that are too short should be ignored.
        if user is None and repo is None and len(num) < bot.config.github.shortest_bare_number:
            return plugin.NOLIMIT

        # All sanity checks done; start filling blanks.
        if user is None and repo is None:
            user, repo = channel_repo.split('/', 1)
        elif repo and not user:
            user, _ = channel_repo.split('/', 1)

        URL = 'https://api.github.com/repos/%s/%s/issues/%s' % (user, repo, num)

    try:
        raw = fetch_api_endpoint(bot, URL)
    except HTTPError:
        bot.say('[GitHub] API returned an error.')
        return plugin.NOLIMIT
    data = json.loads(raw)
    try:
        body = data['body']
    except (KeyError):
        if not suppress_errors:
            bot.say('[GitHub] API says this is an invalid issue. Please report this if you know it should work!')
        return plugin.NOLIMIT

    body = formatting.fmt_short_comment_body(body)

    # what we have so far
    response = [
        bold('[GitHub]'),
        ' [',
        '%s/%s' % (user, repo),
        ' #',
        num,
        '] ',
    ]

    if comment_id:
        # comment format is simple
        response.extend([
            'Comment',
        ])
    else:
        # if it's a link directly to the issue/PR, things are more complicated
        type_ = 'issue'
        state = data['state']

        if 'pull_request' in data:
            type_ = 'PR'

            if state == 'closed' and data['pull_request'].get('merged_at'):
                state = 'merged'

        response.extend([
            state,
            ' ',
            type_,
        ])

    # reunited once again; the rest of the output format is common
    now = datetime.datetime.utcnow()  # can't use trigger.time until it becomes Aware in Sopel 8
    created_at = from_utc(data['created_at'])
    response.extend([
        ' by ',
        data['user']['login'],
        ', created ',
        seconds_to_human((now - created_at).total_seconds()),
        ': ',
    ])

    if ('title' in data):
        # (well, *almost* common)
        response.append(emojize(data['title']))
        response.append(bold(' | '))
    response.append(emojize(body))

    # append link, if not triggered by a link
    if not match:
        response.append(bold(' | '))
        response.append(data['html_url'])

    bot.say(''.join(response))


@plugin.command('gh-repo')
@plugin.example('.gh-repo !clear')
@plugin.example('.gh-repo sopel-irc/sopel-github')
@plugin.require_chanmsg('[GitHub] You can only link a repository to a channel.')
def manage_channel_repo(bot, trigger):
    """
    Set the repository to use for looking up standalone issue/PR references.

    Use the special value ``!clear`` to clear the linked repository.
    """
    allowed = bot.channels[trigger.sender].privileges.get(trigger.nick, 0) >= plugin.OP
    if not allowed and not trigger.admin:
        return bot.say('You must be a channel operator to use this command!')

    if not trigger.group(2):
        msg = 'No repo linked to this channel.'
        current = bot.db.get_channel_value('github_issue_repo', trigger.sender)
        if current:
            msg = 'Issue numbers in %s will fetch data for %s.' % (trigger.sender, current)
        return bot.say(msg)

    if trigger.group(3).lower() == '!clear':
        bot.db.delete_channel_value('github_issue_repo', trigger.sender)
        return bot.say('Cleared linked repo for %s.' % trigger.sender)

    bot.db.set_channel_value('github_issue_repo', trigger.sender, trigger.group(3))
    bot.reply('Set linked repo for %s to %s.' % (trigger.sender, trigger.group(3)))


@plugin.url(commitURL)
def commit_info(bot, trigger, match=None):
    match = match or trigger
    repo = '%s/%s' % (match.group('user'), match.group('repo'))
    URL = 'https://api.github.com/repos/%s/commits/%s' % (repo, match.group('commit'))

    try:
        raw = fetch_api_endpoint(bot, URL)
    except HTTPError:
        bot.say('[GitHub] API returned an error.')
        return plugin.NOLIMIT
    data = json.loads(raw)
    try:
        lines = data['commit']['message'].splitlines()
        if len(lines) > 1:
            body = lines[0] + '…'
        elif len(lines) > 0:
            body = lines[0]
        else:
            body = ''
    except (KeyError):
        bot.say('[GitHub] API says this is an invalid commit. Please report this if you know it\'s a correct link!')
        return plugin.NOLIMIT

    if body.strip() == '':
        body = 'No commit message provided.'

    now = datetime.datetime.utcnow()  # can't use trigger.time until it becomes Aware in Sopel 8
    author_date = from_utc(data['commit']['author']['date'])
    committer_date = from_utc(data['commit']['committer']['date'])

    change_count = data['stats']['total']
    file_count = len(data['files'])
    response = [
        bold('[GitHub]'),
        ' [',
        repo,
        '] ',
        data['author']['login'] if data['author'] else data['commit']['author']['name'],
        ': ',
        body,
        bold(' | '),
        str(change_count),
        ' change' if change_count == 1 else ' changes',
        ' in ',
        str(file_count),
        ' file' if file_count == 1 else ' files',
        bold(' | '),
        'Authored ' + seconds_to_human((now - author_date).total_seconds()),
        bold(' | '),
        'Committed ' + seconds_to_human((now - committer_date).total_seconds()),
    ]
    bot.say(''.join(response))


@plugin.url(contentURL)
def file_info(bot, trigger, match=None):
    match = match or trigger
    repo = '%s/%s' % (match.group('user'), match.group('repo'))
    path = match.group('path')
    ref = match.group('ref')
    start_line = match.group('start')
    end_line = match.group('end')

    URL = 'https://api.github.com/repos/%s/contents/%s?ref=%s' % (repo, path, ref)

    try:
        raw = fetch_api_endpoint(bot, URL)
    except HTTPError:
        bot.say('[GitHub] API returned an error.')
        return plugin.NOLIMIT
    data = json.loads(raw)

    if not isinstance(data, Mapping) or data.get('type', 'fakenews') != 'file':
        # silently ignore directory contents (and unexpected responses) for now
        return plugin.NOLIMIT

    response = [
        bold('[GitHub]'),
        ' [',
        repo,
        '] ',
        data['path'],
        ' @ ',
        ref,
    ]

    if start_line:
        lines = base64.b64decode(data['content']).splitlines()

        try:
            snippet = lines[int(start_line) - 1].decode('utf-8')
        except (IndexError, UnicodeDecodeError):
            # Line doesn't exist, or not a text file
            snippet = None

        if snippet:
            response.extend([
                ' | L',
                start_line,
                ': ',
                monospace(snippet),
                ' […] (to L%s)' % end_line if end_line else '',
            ])

    bot.say(''.join(response))


def get_data(bot, trigger, URL):
    URL = URL.split('#')[0]
    try:
        raw = fetch_api_endpoint(bot, URL)
        rawLang = fetch_api_endpoint(bot, URL + '/languages')
    except HTTPError:
        bot.say('[GitHub] API returned an error.')
        return plugin.NOLIMIT
    data = json.loads(raw)
    langData = list(json.loads(rawLang).items())
    langData = sorted(langData, key=operator.itemgetter(1), reverse=True)

    if 'message' in data:
        return bot.say('[GitHub] %s' % data['message'])

    langColors = deque(['12', '08', '09', '13'])

    max = sum([pair[1] for pair in langData])

    data['language'] = ''
    for (key, val) in langData[:3]:
        data['language'] = data['language'] + color(str("{0:.1f}".format(float(val) / max * 100)) + '% ' + key, langColors[0]) + ' '
        langColors.rotate()

    if len(langData) > 3:
        remainder = sum([pair[1] for pair in langData[3:]])
        data['language'] = data['language'] + color(str("{0:.1f}".format(float(remainder) / max * 100)) + '% Other', langColors[0]) + ' '

    timezone = get_timezone(bot.db, bot.config, None, trigger.nick)
    if not timezone:
        timezone = 'UTC'
    data['pushed_at'] = format_time(bot.db, bot.config, timezone, trigger.nick, trigger.sender, from_utc(data['pushed_at']))

    return data


@plugin.url(repoURL)
def repo_info(bot, trigger, match=None):
    URL = 'https://api.github.com/repos/%s/%s' % (match.group('user'), match.group('repo'))
    fmt_response(bot, trigger, URL, True)


@plugin.command('github', 'gh')
@plugin.example('.gh sopel-irc/sopel-github')
def github_repo(bot, trigger):
    repo = trigger.group(3) or None

    if repo is None:
        return bot.reply('I need a repository name, or `user/reponame`.')

    if repo.lower() == 'version':
        pfx = bot.settings.core.help_prefix
        msg = "Sorry, the `{pfx}gh version` command is deprecated. "

        if bot.has_plugin('version'):
            msg += "Try `{pfx}version github` instead!"
        else:
            msg += "Ask my owner about the `version` plugin!"

        bot.reply(msg.format(pfx=pfx))
        return plugin.NOLIMIT

    if repo.lower() == 'status':
        # This was previously more complex, but broke sometime before June 2024.
        # It could be re-improved using other API endpoints documented here:
        # https://www.githubstatus.com/api
        current = json.loads(requests.get('https://www.githubstatus.com/api/v2/status.json').text)
        return bot.say('[GitHub] Current Status: ' + current['status']['description'])
    elif repo.lower() == 'rate-limit':
        return bot.say(fetch_api_endpoint(bot, 'https://api.github.com/rate_limit'))

    if '/' not in repo:
        repo = trigger.nick.strip() + '/' + repo
    URL = 'https://api.github.com/repos/%s' % (repo.strip())

    fmt_response(bot, trigger, URL)


def from_utc(utcTime, fmt="%Y-%m-%dT%H:%M:%SZ"):
    """
    Convert UTC time string to time.struct_time
    """
    return datetime.datetime.strptime(utcTime, fmt)


def fmt_response(bot, trigger, URL, from_regex=False):
    data = get_data(bot, trigger, URL)

    if not data:
        return

    response = [
        bold('[GitHub]'),
        ' ',
        str(data['full_name'])
    ]

    if data['description'] != None:
        response.append(' - ' + str(emojize(data['description'])))

    if not data['language'].strip() == '':
        response.extend([' | ', data['language'].strip()])

    response.extend([
        ' | Last Push: ',
        str(data['pushed_at']),
        ' | Stargazers: ',
        str(data['stargazers_count']),
        ' | Watchers: ',
        str(data['subscribers_count']),
        ' | Forks: ',
        str(data['forks_count']),
        ' | Network: ',
        str(data['network_count']),
        ' | Open Issues: ',
        str(data['open_issues'])
    ])

    if not from_regex:
        response.extend([' | ', data['html_url']])

    bot.say(''.join(response))


@plugin.command('gh-hook')
@plugin.require_chanmsg('[GitHub] GitHub hooks can only be configured in a channel')
@plugin.example('.gh-hook maxpowa/Inumuta enable')
def configure_repo_messages(bot, trigger):
    '''
    .gh-hook <repo> [enable|disable] - Enable/disable displaying webhooks from repo in current channel (You must be a channel OP)
    Repo notation is just <user/org>/<repo>, not the whole URL.
    '''
    allowed = bot.channels[trigger.sender].privileges.get(trigger.nick, 0) >= plugin.OP
    if not allowed and not trigger.admin:
        return bot.say('You must be a channel operator to use this command!')

    if not trigger.group(2):
        return bot.say(configure_repo_messages.__doc__.strip())

    channel = trigger.sender.lower()
    repo_name = trigger.group(3).lower()

    if not '/' in repo_name or 'http://' in repo_name or 'https://' in repo_name:
        return bot.say('Invalid repo formatting, see "{}help gh-hook" for an example'.format(bot.config.core.help_prefix))

    enabled = True if not trigger.group(4) or trigger.group(4).lower() == 'enable' else False

    auth_data = {
        'client_id': bot.config.github.client_id,
        'scope': 'write:repo_hook',
        'state': '{}:{}'.format(repo_name, channel)}
    auth_url = 'https://github.com/login/oauth/authorize?{}'.format(urlencode(auth_data))

    conn = bot.db.connect()
    c = conn.cursor()

    c.execute('SELECT * FROM gh_hooks WHERE channel = ? AND repo_name = ?', (channel, repo_name))
    result = c.fetchone()
    if not result:
        c.execute('''INSERT INTO gh_hooks (channel, repo_name, enabled) VALUES (?, ?, ?)''', (channel, repo_name, enabled))
        bot.say("Successfully enabled listening for {repo}'s events in {chan}.".format(chan=channel, repo=repo_name))
        bot.say('Great! Please allow me to create my webhook by authorizing via this link:')
        bot.say(auth_url, max_messages=10)
        bot.say('Once that webhook is successfully created, I\'ll post a message in here. Give me about a minute or so to set it up after you authorize. You can configure the colors that I use to display webhooks with {}gh-hook-color'.format(bot.config.core.help_prefix))
    else:
        c.execute('''UPDATE gh_hooks SET enabled = ? WHERE channel = ? AND repo_name = ?''', (enabled, channel, repo_name))
        bot.say("Successfully {state} the subscription to {repo}'s events".format(state='enabled' if enabled else 'disabled', repo=repo_name))
        if enabled:
            bot.say('Great! Please allow me to create my webhook by authorizing via this link:')
            bot.say(auth_url, max_messages=10)
            bot.say('Once that webhook is successfully created, I\'ll post a message in here. Give me about a minute or so to set it up after you authorize. You can configure the colors that I use to display webhooks with {}gh-hook-color'.format(bot.config.core.help_prefix))
    conn.commit()
    conn.close()


@plugin.command('gh-hook-color')
@plugin.require_chanmsg('[GitHub] GitHub hooks can only be configured in a channel')
@plugin.example('.gh-hook-color maxpowa/Inumuta 13 15 6 6 14 2')
def configure_repo_colors(bot, trigger):
    '''
    .gh-hook-color <repo> <repo color> <name color> <branch color> <tag color> <hash color> <url color> - Set custom colors for the webhook messages (Uses mIRC color indicies)
    '''
    allowed = bot.channels[trigger.sender].privileges.get(trigger.nick, 0) >= plugin.OP
    if not allowed and not trigger.admin:
        return bot.say('You must be a channel operator to use this command!')

    if not trigger.group(2):
        return bot.say(configure_repo_colors.__doc__.strip())

    channel = trigger.sender.lower()
    repo_name = trigger.group(3).lower()
    colors = []
    try:
        colors = [int(c) % 16 for c in trigger.group(2).replace(trigger.group(3), '', 1).split()]
    except:
        return bot.say('You must provide exactly 6 colors that are integers and are space separated. See "{}help gh-hook-color" for more information.'.format(bot.config.core.help_prefix))

    if len(colors) != 6:
        return bot.say('You must provide exactly 6 colors! See "{}help gh-hook-color" for more information.'.format(bot.config.core.help_prefix))

    conn = bot.db.connect()
    c = conn.cursor()

    c.execute('SELECT * FROM gh_hooks WHERE channel = ? AND repo_name = ?', (channel, repo_name))
    result = c.fetchone()
    if not result:
        return bot.say('Please use "{}gh-hook {} enable" before attempting to configure colors!'.format(bot.config.core.help_prefix, repo_name))
    else:
        combined = colors
        combined.append(channel)
        combined.append(repo_name)
        c.execute('''UPDATE gh_hooks SET repo_color = ?, name_color = ?, branch_color = ?, tag_color = ?,
                     hash_color = ?, url_color = ? WHERE channel = ? AND repo_name = ?''', combined)
        conn.commit()
        c.execute('SELECT * FROM gh_hooks WHERE channel = ? AND repo_name = ?', (channel, repo_name))
        row = c.fetchone()
        bot.say("[{}] Example name: {} tag: {} commit: {} branch: {} url: {}".format(
                formatting.fmt_repo(repo_name, row),
                formatting.fmt_name(trigger.nick, row),
                formatting.fmt_tag('tag', row),
                formatting.fmt_hash('c0mm17', row),
                formatting.fmt_branch('master', row),
                formatting.fmt_url('http://git.io/', row)))
