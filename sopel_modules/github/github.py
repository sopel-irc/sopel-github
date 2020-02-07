# coding=utf8
"""
github.py - Sopel GitHub Module
Copyright 2015 Max Gurela
Copyright 2019 dgw, Rusty Bower

 _______ __ __   __           __
|     __|__|  |_|  |--.--.--.|  |--.
|    |  |  |   _|     |  |  ||  _  |
|_______|__|____|__|__|_____||_____|

"""

from __future__ import unicode_literals
from sopel import tools
from sopel.module import commands, rule, OP, NOLIMIT, example, require_chanmsg
from sopel.formatting import bold, color
from sopel.tools.time import get_timezone, format_time
from sopel.config.types import StaticSection, ValidatedAttribute

from . import formatting
from .formatting import shorten_url, emojize
from .utils import get_db_session
from .webhook import setup_webhook, shutdown_webhook, GithubHooks

from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import scoped_session, sessionmaker

import operator
from collections import deque

import sys
if sys.version_info.major < 3:
    from urllib import urlencode
    from urllib2 import HTTPError
else:
    from urllib.parse import urlencode
    from urllib.error import HTTPError
import json
import requests
import re
import datetime

'''
 _______           __         __
|   |   |.-----.--|  |.--.--.|  |.-----.
|       ||  _  |  _  ||  |  ||  ||  -__|
|__|_|__||_____|_____||_____||__||_____|

'''

# GitHub enforces alphanumeric usernames, and allows only one punctuation character: hyphen ('-')
# Regex copied and slightly modified to meet our needs from CC0 source:
# https://github.com/shinnn/github-username-regex/blob/0794566cc10e8c5a0e562823f8f8e99fa044e5f4/module.js#L1
githubUsername = r'[A-Za-z\d](?:[A-Za-z\d]|-(?=[A-Za-z\d])){0,38}'
# GitHub additionally allows dots ('.') in repo names, as well as hyphens
# not copied from anywhere, but handy to simply reuse
githubRepoSlug = r'[A-Za-z0-9\.\-]+'
# lots of regex and other globals to make this stuff work
baseURL = r'https?://(?:www\.)?github.com/({username}/{repo})'.format(username=githubUsername, repo=githubRepoSlug)
repoURL = baseURL + r'/?(?!\S)'
issueURL = baseURL + r'/(?:issues|pull)/([\d]+)(?:#issuecomment-([\d]+))?'
commitURL = baseURL + r'/(?:commit)/([A-z0-9\-]+)'
repoRegex = re.compile(repoURL)
issueRegex = re.compile(issueURL)
commitRegex = re.compile(commitURL)
sopel_instance = None


class GitHubSection(StaticSection):
    client_id = ValidatedAttribute('client_id', default=None)
    client_secret = ValidatedAttribute('client_secret', default=None)
    secret = ValidatedAttribute('secret', default=None)  # TODO remove in 0.3.0 or thereabouts
    webhook = ValidatedAttribute('webhook', bool, default=False)
    webhook_host = ValidatedAttribute('webhook_host', default='0.0.0.0')
    webhook_port = ValidatedAttribute('webhook_port', default='3333')
    external_url = ValidatedAttribute('external_url', default='http://your_ip_or_domain_here:3333')


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
    if 'url_callbacks' not in sopel.memory:
        sopel.memory['url_callbacks'] = tools.SopelMemory()
    sopel.memory['url_callbacks'][repoRegex] = repo_info
    sopel.memory['url_callbacks'][issueRegex] = issue_info
    sopel.memory['url_callbacks'][commitRegex] = commit_info

    if sopel.config.github.webhook:
        setup_webhook(sopel)

    if not sopel.config.github.client_secret:
        if sopel.config.github.secret:
            sopel.config.github.client_secret = sopel.config.github.secret
            del sopel.config.github.secret
            sopel.config.save()
            tools.stderr("[GitHub] Migrated `secret` to `client_secret` in config.")


def shutdown(sopel):
    del sopel.memory['url_callbacks'][repoRegex]
    del sopel.memory['url_callbacks'][issueRegex]
    del sopel.memory['url_callbacks'][commitRegex]
    shutdown_webhook(sopel)

'''
 _______ ______ _____        ______                    __
|   |   |   __ |     |_     |   __ |.---.-.----.-----.|__|.-----.-----.
|   |   |      <       |    |    __||  _  |   _|__ --||  ||     |  _  |
|_______|___|__|_______|    |___|   |___._|__| |_____||__||__|__|___  |
                                                                |_____|
'''


def get_db_session(bot):
    try:
        engine = bot.db.connect()
    except OperationalError:
        print("OperationalError: Unable to connect to database.")
        raise

    return scoped_session(sessionmaker(bind=engine))


def fetch_api_endpoint(bot, url):
    oauth = ''
    if bot.config.github.client_id and bot.config.github.client_secret:
        oauth = '?client_id=%s&client_secret=%s' % (bot.config.github.client_id, bot.config.github.client_secret)
    return requests.get(url + oauth).text


@rule('.*%s.*' % issueURL)
def issue_info(bot, trigger, match=None):
    match = match or trigger
    URL = 'https://api.github.com/repos/%s/issues/%s' % (match.group(1), match.group(2))
    if (match.group(3)):
        URL = 'https://api.github.com/repos/%s/issues/comments/%s' % (match.group(1), match.group(3))

    try:
        raw = fetch_api_endpoint(bot, URL)
    except HTTPError:
        bot.say('[GitHub] API returned an error.')
        return NOLIMIT
    data = json.loads(raw)
    try:
        body = formatting.fmt_short_comment_body(data['body'])
    except (KeyError):
        bot.say('[GitHub] API says this is an invalid issue. Please report this if you know it\'s a correct link!')
        return NOLIMIT

    if body.strip() == '':
        body = 'No description provided.'

    response = [
        bold('[GitHub]'),
        ' [',
        match.group(1),
        ' #',
        match.group(2),
        '] ',
        data['user']['login'],
        ': '
    ]

    if ('title' in data):
        response.append(emojize(data['title']))
        response.append(bold(' | '))
    response.append(emojize(body))

    bot.say(''.join(response))


@rule('.*%s.*' % commitURL)
def commit_info(bot, trigger, match=None):
    match = match or trigger
    URL = 'https://api.github.com/repos/%s/commits/%s' % (match.group(1), match.group(2))

    try:
        raw = fetch_api_endpoint(bot, URL)
    except HTTPError:
        bot.say('[GitHub] API returned an error.')
        return NOLIMIT
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
        return NOLIMIT

    if body.strip() == '':
        body = 'No commit message provided.'

    file_count = len(data['files'])
    response = [
        bold('[GitHub]'),
        ' [',
        match.group(1),
        '] ',
        data['author']['login'] if data['author'] else data['commit']['author']['name'],
        ': ',
        body,
        bold(' | '),
        str(data['stats']['total']),
        ' changes in ',
        str(file_count),
        ' file' if file_count == 1 else ' files'
    ]
    bot.say(''.join(response))


def get_data(bot, trigger, URL):
    URL = URL.split('#')[0]
    try:
        raw = fetch_api_endpoint(bot, URL)
        rawLang = fetch_api_endpoint(bot, URL + '/languages')
    except HTTPError:
        bot.say('[GitHub] API returned an error.')
        return NOLIMIT
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


@rule('.*%s.*' % repoURL)
def repo_info(bot, trigger):
    user, repo = [s.strip() for s in trigger.group(1).split('/', 1)]
    URL = 'https://api.github.com/repos/%s/%s' % (user, repo)
    fmt_response(bot, trigger, URL, True)


@commands('github', 'gh')
def github_repo(bot, trigger, match=None):
    match = match or trigger
    repo = match.group(2) or match.group(1)

    if repo.lower() == 'version':
        return bot.say('[GitHub] Version {} by {}, report issues at {}'.format(
            github.__version__, github.__author__, github.__repo__))

    if repo.lower() == 'status':
        current = json.loads(requests.get('https://status.github.com/api/status.json').text)
        lastcomm = json.loads(requests.get('https://status.github.com/api/last-message.json').text)

        status = current['status']
        if status == 'major':
            status = "\x02\x034Broken\x03\x02"
        elif status == 'minor':
            status = "\x02\x037Shakey\x03\x02"
        elif status == 'good':
            status = "\x02\x033Online\x03\x02"

        lstatus = lastcomm['status']
        if lstatus == 'major':
            lstatus = "\x02\x034Broken\x03\x02"
        elif lstatus == 'minor':
            lstatus = "\x02\x037Shakey\x03\x02"
        elif lstatus == 'good':
            lstatus = "\x02\x033Online\x03\x02"

        timezone = get_timezone(bot.db, bot.config, None, trigger.nick)
        if not timezone:
            timezone = 'UTC'
        lastcomm['created_on'] = format_time(bot.db, bot.config, timezone, trigger.nick, trigger.sender, from_utc(lastcomm['created_on']))

        return bot.say('[GitHub] Current Status: ' + status + ' | Last Message: ' + lstatus + ': ' + lastcomm['body'] + ' (' + lastcomm['created_on'] + ')')
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


@commands('gh-hook')
@require_chanmsg('[GitHub] GitHub hooks can only be configured in a channel')
@example('.gh-hook maxpowa/Inumuta enable')
def configure_repo_messages(bot, trigger):
    '''
    .gh-hook <repo> [enable|disable] - Enable/disable displaying webhooks from repo in current channel (You must be a channel OP)
    Repo notation is just <user/org>/<repo>, not the whole URL.
    '''
    allowed = bot.privileges[trigger.sender].get(trigger.nick, 0) >= OP
    if not allowed and not trigger.admin:
        return bot.msg(trigger.sender, 'You must be a channel operator to use this command!')

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

    session = get_db_session(bot)

    try:
        hook = session.query(GithubHooks) \
            .filter(GithubHooks.channel == channel) \
            .filter(GithubHooks.repo_name == repo_name) \
            .one_or_none()
        if hook is None:
            hook = GithubHooks(channel=channel, repo_name=repo_name, enabled=enabled)
            session.add(hook)
            session.commit()

            bot.say("Successfully enabled listening for {repo}'s events in {chan}.".format(chan=channel, repo=repo_name))
            bot.say('Great! Please allow me to create my webhook by authorizing via this link: ' + shorten_url(auth_url))
            bot.say('Once that webhook is successfully created, I\'ll post a message in here. Give me about a minute or so to set it up after you authorize. You can configure the colors that I use to display webhooks with {}gh-hook-color'.format(bot.config.core.help_prefix))
        else:
            hook.channel = channel
            hook.repo_name = repo_name
            hook.enabled = enabled
            session.commit()

            bot.say("Successfully {state} the subscription to {repo}'s events".format(state='enabled' if enabled else 'disabled', repo=repo_name))
            if enabled:
                bot.say('Great! Please allow me to create my webhook by authorizing via this link: ' + shorten_url(auth_url))
                bot.say('Once that webhook is successfully created, I\'ll post a message in here. Give me about a minute or so to set it up after you authorize. You can configure the colors that I use to display webhooks with {}gh-hook-color'.format(bot.config.core.help_prefix))
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


@commands('gh-hook-color')
@require_chanmsg('[GitHub] GitHub hooks can only be configured in a channel')
@example('.gh-hook-color maxpowa/Inumuta 13 15 6 6 14 2')
def configure_repo_colors(bot, trigger):
    """
    .gh-hook-color <repo> <repo color> <name color> <branch color> <tag color> <hash color> <url color> - Set custom colors for the webhook messages (Uses mIRC color indicies)
    """
    allowed = bot.privileges[trigger.sender].get(trigger.nick, 0) >= OP
    if not allowed and not trigger.admin:
        return bot.msg(trigger.sender, 'You must be a channel operator to use this command!')

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

    session = get_db_session(bot)

    try:
        hook = session.query(GithubHooks) \
            .filter(GithubHooks.channel == channel) \
            .filter(GithubHooks.repo_name == repo_name) \
            .one_or_none()
        if hook is None:
            return bot.say('Please use "{}gh-hook {} enable" before attempting to configure colors!'.format(bot.config.core.help_prefix, repo_name))
        else:
            hook.channel = channel
            hook.repo_name = repo_name
            hook.repo_color = colors[0]
            hook.name_color = colors[1]
            hook.branch_color = colors[2]
            hook.tag_color = colors[3]
            hook.hash_color = colors[4]
            hook.url_color = colors[5]
            session.commit()

            row = session.query(GithubHooks) \
               .filter(GithubHooks.channel == channel) \
               .filter(GithubHooks.repo_name == repo_name) \
               .one_or_none()

            bot.say("[{}] Example name: {} tag: {} commit: {} branch: {} url: {}".format(
                    formatting.fmt_repo(repo_name, row),
                    formatting.fmt_name(trigger.nick, row),
                    formatting.fmt_tag('tag', row),
                    formatting.fmt_hash('c0mm17', row),
                    formatting.fmt_branch('master', row),
                    formatting.fmt_url('https://git.io/', row)))
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()
