# coding=utf8
"""
webhook.py - Sopel GitHub Module
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

from sopel import tools
from sopel.formatting import bold, color
from sopel.tools.time import get_timezone, format_time

from .formatting import get_formatted_response
from .formatting import fmt_repo
from .formatting import fmt_name

from threading import Thread
import bottle
import json
import requests

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
    if 'gh_webhook_server' in sopel.memory:
        print('Stopping webhook server')
        sopel.memory['gh_webhook_server'].stop()
        sopel.memory['gh_webhook_thread'].join()
        print('GitHub webhook shutdown complete')


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
    c.execute('SELECT * FROM gh_hooks WHERE repo_name = ? AND enabled = 1', (repo.lower(), ))
    return c.fetchall()


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
    raw = requests.post('https://github.com/login/oauth/access_token', data=data, headers={'Accept': 'application/json'})
    try:
        res = json.loads(raw.text)

        if 'scope' not in res:
            raise ValueError('You\'ve already completed authorization on this repo')
        if 'write:repo_hook' not in res['scope']:
            raise ValueError('You didn\'t allow read/write on repo hooks!')

        access_token = res['access_token']

        data = {
            "name": "web",
            "active": True,
            "events": ["*"],
            "config": {
                "url": sopel_instance.config.github.external_url,
                "content_type": "json"
            }
        }

        raw = requests.post('https://api.github.com/repos/{}/hooks?access_token={}'.format(repo, access_token), data=json.dumps(data))
        res = json.loads(raw.text)

        if 'ping_url' not in res:
            if 'errors' in res:
                raise ValueError(', '.join([error['message'] for error in res['errors']]))
            else:
                raise ValueError('Webhook creation failed, try again.')

        raw = requests.get(res['ping_url'] + '?access_token={}'.format(access_token))

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
