# coding=utf8
"""
webhook.py - Sopel Github Module
Copyright 2015 Max Gurela

 _______ __ __   __           __
|     __|__|  |_|  |--.--.--.|  |--.
|    |  |  |   _|     |  |  ||  _  |
|_______|__|____|__|__|_____||_____|
 ________         __     __                 __
|  |  |  |.-----.|  |--.|  |--.-----.-----.|  |--.-----.
|  |  |  ||  -__||  _  ||     |  _  |  _  ||    <|__ --|
|________||_____||_____||__|__|_____|_____||__|__|_____|

"""

from __future__ import unicode_literals

from sopel import web, tools
from sopel.formatting import bold, color
from sopel.tools.time import get_timezone, format_time

from github.formatting import get_formatted_response

from threading import Thread
import bottle

# Because I'm a horrible person
sopel_instance = None

def setup_webhook(sopel):
    global sopel_instance
    sopel_instance = sopel
    host = sopel.config.github.webhook_host
    port = sopel.config.github.webhook_port

    base = StoppableWSGIRefServer(host=host, port=port)
    server = Thread(target=bottle.run, kwargs={'server': base})
    server.setDaemon(True)
    server.start()
    sopel.memory['gh_webhook_server'] = base
    sopel.memory['gh_webhook_thread'] = server

    conn = sopel.db.connect()
    c = conn.cursor()

    try:
        c.execute('SELECT * FROM gh_hooks')
    except Exception:
        create_table(sopel, c)
        conn.commit()
    conn.close()


def create_table(bot, c):
    primary_key = '(channel, repo_name)'

    c.execute('''CREATE TABLE IF NOT EXISTS gh_hooks (
        channel TEXT,
        repo_name TEXT,
        enabled BOOL DEFAULT 1,
        url_color TINYINT DEFAULT 2,
        tag_color TINYINT DEFAULT 6,
        repo_color TINYINT DEFAULT 13,
        name_color TINYINT DEFAULT 15,
        hash_color TINYINT DEFAULT 14,
        branch_color TINYINT DEFAULT 6,
        PRIMARY KEY {0}
        )'''.format(primary_key))


def shutdown_webhook(sopel):
    global sopel_instance
    sopel_instance = None
    if sopel.memory.contains('gh_webhook_server'):
        print('Stopping webhook server')
        sopel.memory['gh_webhook_server'].stop()
        sopel.memory['gh_webhook_thread'].join()
        print('Github webhook shutdown complete')


class StoppableWSGIRefServer(bottle.ServerAdapter):
    server = None

    def run(self, handler):
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        if self.quiet:
            class QuietHandler(WSGIRequestHandler):
                def log_request(*args, **kw):
                    pass
            self.options['handler_class'] = QuietHandler
        self.server = make_server(self.host, self.port, handler, **self.options)
        self.server.serve_forever()

    def stop(self):
        self.server.shutdown()


def get_targets(repo):
    conn = sopel_instance.db.connect()
    c = conn.cursor()

    #sopel_instance.msg('#Inumuta', 'Checking db for '+repo)
    c.execute('SELECT * FROM gh_hooks WHERE repo_name = ? AND enabled = 1', (repo.lower(), ))
    result = c.fetchall()
    #sopel_instance.msg('#Inumuta', 'Result: '+json.dumps(result))
    return result


@bottle.get("/webhook")
def show_hook_info():
    return 'Listening for webhook connections!'


@bottle.post("/webhook")
def webhook():
    event = bottle.request.headers.get('X-GitHub-Event') or 'ping'

    try:
        payload = bottle.request.json
    except:
        return bottle.abort(400, 'Something went wrong!')

    if event == 'ping':
        channels = get_targets(payload['repository']['full_name'])
        for chan in channels:
            sopel_instance.msg(chan[0], '[{}] {}: {} (Your webhook is now enabled)'.format(
                          fmt_repo(payload['repository']['name'], chan),
                          fmt_name(payload['sender']['login'], chan),
                          payload['zen']))
        return '{"channels":' + json.dumps([chan[0] for chan in channels]) + '}'

    payload['event'] = event

    targets = get_targets(payload['repository']['full_name'])

    for row in targets:
        messages = get_formatted_response(payload, row)
        # Write the formatted message(s) to the channel
        for message in messages:
            sopel_instance.msg(row[0], message)

    return '{"channels":' + json.dumps([chan[0] for chan in targets]) + '}'


@bottle.get('/auth')
def handle_auth_response():
    code = bottle.request.query.code
    state = bottle.request.query.state

    repo = state.split(':')[0]
    channel = state.split(':')[1]

    data = {'client_id': sopel_instance.config.github.client_id,
             'client_secret': sopel_instance.config.github.secret,
             'code': code}
    raw = web.post('https://github.com/login/oauth/access_token', data, headers={'Accept': 'application/json'})
    try:
        res = json.loads(raw)

        if 'scope' not in res:
            raise ValueError('You\'ve already completed authorization on this repo')
        if 'write:repo_hook' not in res['scope']:
            raise ValueError('You didn\'t allow read/write on repo hooks!')

        access_token = res['access_token']

        data = {
            "name": "web",
            "active": "true",
            "events": ["*"],
            "config": {
                "url": "http://xpw.us/webhook",
                "content_type": "json"
            }
        }

        raw = web.post('https://api.github.com/repos/{}/hooks?access_token={}'.format(repo, access_token), json.dumps(data))
        res = json.loads(raw)

        if 'ping_url' not in res:
            if 'errors' in res:
                raise ValueError(', '.join([error['message'] for error in res['errors']]))
            else:
                raise ValueError('Webhook creation failed, try again.')

        raw, headers = web.get(res['ping_url'] + '?access_token={}'.format(access_token), return_headers=True)

        title = 'Done!'
        header = 'Webhook setup complete!'
        body = 'That was simple, right?! You should be seeing a completion message in {} any second now'.format(channel)
        flair = 'There\'s no way it was that easy... things are never this easy...'
    except Exception as e:
        title = 'Error!'
        header = 'Webhook setup failed!'
        body = 'Please try using the link in {} again, something went wrong!'.format(channel)
        flair = str(e)

    page = '''
<!DOCTYPE html>
<html>
  <head>
    <title>{title}</title>
    <style>
      body {{
        width: 35em;
        margin: 0 auto;
        font-family: Tahoma, Verdana, Arial, sans-serif;
      }}
    </style>
  </head>
  <body>
    <h1>{header}</h1>
    <p>{body}</p>
    <small><em>{flair}</em></small>
  </body>
</html>
    '''

    return page.format(title=title, header=header, body=body, flair=flair)


@commands('gh-hook')
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
        return bot.say('Invalid repo formatting, see ".help gh-hook" for an example')

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
        bot.say('Great! Please allow me to create my webhook by authorizing via this link: ' + shorten_url(auth_url))
        bot.say('Once that webhook is successfully created, I\'ll post a message in here. Give me about a minute or so to set it up after you authorize. You can configure the colors that I use to display webhooks with .gh-hook-color')
    else:
        c.execute('''UPDATE gh_hooks SET enabled = ? WHERE channel = ? AND repo_name = ?''', (enabled, channel, repo_name))
        bot.say("Successfully {state} the subscription to {repo}'s events".format(state='enabled' if enabled else 'disabled', repo=repo_name))
        if enabled:
            bot.say('Great! Please allow me to create my webhook by authorizing via this link: ' + shorten_url(auth_url))
            bot.say('Once that webhook is successfully created, I\'ll post a message in here. Give me about a minute or so to set it up after you authorize. You can configure the colors that I use to display webhooks with .gh-hook-color')
    conn.commit()
    conn.close()


@commands('gh-hook-color')
@example('.gh-hook-color maxpowa/Inumuta 13 15 6 6 14 2')
def configure_repo_colors(bot, trigger):
    '''
    .gh-hook-color <repo> <repo color> <name color> <branch color> <tag color> <hash color> <url color> - Set custom colors for the webhook messages (Uses mIRC color indicies)
    '''
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
        return bot.say('You must provide exactly 6 colors that are integers and are space separated. See ".help gh-hook-color" for more information.')

    if len(colors) != 6:
        return bot.say('You must provide exactly 6 colors! See ".help gh-hook-color" for more information.')

    conn = bot.db.connect()
    c = conn.cursor()

    c.execute('SELECT * FROM gh_hooks WHERE channel = ? AND repo_name = ?', (channel, repo_name))
    result = c.fetchone()
    if not result:
        return bot.say('Please use ".gh-hook {} enable" before attempting to configure colors!'.format(repo_name))
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
                fmt_repo(repo_name, row),
                fmt_name(trigger.nick, row),
                fmt_tag('tag', row),
                fmt_hash('c0mm17', row),
                fmt_branch('master', row),
                fmt_url('http://git.io/', row)))

