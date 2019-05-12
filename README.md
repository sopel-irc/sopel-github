# Sopel GitHub

GitHub plugin for [Sopel](https://sopel.chat/) IRC bots.


## Installation

The easy (and recommended) way: `pip install sopel_modules.github`

The less-easy way; you must already have Sopel installed to use this method.
```
git clone https://github.com/sopel-irc/sopel-github
cd sopel-github
pip install .
```

## Out-of-the-box Functionality

Detects when GitHub URLs are posted and takes over URL handling of them, pretty
printing details of:

 * Commits
 * Issues
 * Issue Comments
 * Pull Requests
 * Repositories

Pretty prints repository details on command, using `.gh user/repo` or `.github
user/repo`. If you omit the user, it will assume your IRC nick is the user. For
example:

```
<@maxpowa> .gh sopel-github
<Sopel> [GitHub] maxpowa/sopel-github - GitHub module for Sopel | 100.0% Python
        | Last Push: 2015-10-16 - 04:00:32UTC | Stargazers: 0 | Watchers: 0 |
        Forks: 0 | Network: 8 | Open Issues: 0 |
        https://github.com/maxpowa/sopel-github

<+salty> .gh sopel-irc/sopel-github
<Sopel> [GitHub] sopel-irc/sopel-github - GitHub module for Sopel | 100.0%
        Python | Last Push: Sunday, May 12, 2019 17:05:43 (CDT) | Stargazers: 3
        | Watchers: 1 | Forks: 8 | Network: 8 | Open Issues: 18 |
        https://github.com/sopel-irc/sopel-github
```

### API Keys & Usage

GitHub APIs have some fairly lenient unauthorized request limits, but you may
find yourself hitting them. In order to prevent yourself from hitting these
limits (and potentially being blacklisted), you should generate GitHub API keys
for yourself. Fill out the information at
https://github.com/settings/applications/new and then populate your
configuration with your newly generated client key and secret.

__IF YOU PLAN ON USING WEBHOOK FUNCTIONALITY:__ You _must_ properly fill out the
"Authorization callback URL" to match the external URL you plan to use for the
webhook.


## Webhook Functionality

Webhook functionality is __disabled__ by default. It requires slightly more
technical knowledge and configuration may vary depending on your system. There's
two ways this may be configured, behind a proxy or exposed to the web.


#### Configuring behind a proxy

This is the __recommended__ way of configuring the webhook functionality, as
there may be security flaws in the other method.

First, configure the GitHub module. You may do so by running `sopel
--configure-modules` or changing the config file directly.
```
[github]
webhook = True
webhook_host = 127.0.0.1
webhook_port = 3333
external_url = http://bad.code.brought.to.you.by.maxpowa.us/webhook
```
The above configuration is only listening on `localhost (127.0.0.1)`, because
I'm using a reverse proxy in nginx to proxy `/webhook` to port 3333. The reverse
proxy configuration would be fairly simple, as shown below. Auth must be
included, to match the "Authorization callback URL" you included in generating
the API keys.
```
location ~ /(webhook|auth) {
    proxy_pass http://127.0.0.1:3333;
}
``` 

#### Configuring exposed to the web

If you're not using a proxy, your config will look something like the below
config.
```
[github]
webhook = True
webhook_host = 0.0.0.0  # Or a specific interface
webhook_port = 3333
external_url = http://your.ip.here:3333/webhook
```

### Creating hooks

As an OP+ in a channel, you may type `.gh-hook user/repo`. You will see some
informational text on what you need to do to finalize the hook, including a link
to click to authorize the creation of the webhook. You will be required to
authorize the GitHub application to read/write your webhooks (see
[L163-164](https://github.com/sopel-irc/sopel-github/blob/9afaf1e51d9c28a1bbba7b442f6e7dea7db74018/sopel_modules/github/webhook.py#L163-L164))
but this should be the _only_ permissions we need.

```
<@maxpowa> .gh-hook maxpowa/sopel-github
<Sopel> Successfully enabled listening for maxpowa/sopel-github's events in
        #inumuta.
<Sopel> Great! Please allow me to create my webhook by authorizing via this
        link: <git.io link>
<Sopel> Once that webhook is successfully created, I'll post a message in here.
        Give me about a minute or so to set it up after you authorize. You can
        configure the colors that I use to display webhooks with .gh-hook-color
```

After you've authorized the webhook creation, you will be redirected to a simple
page informing you that the bot succeeded/failed creating your hook. Assuming it
succeeded, you should see a generic message appear in the channel you activated
it in.


### Customizing hooks

You may customize the colors that each part of the hook takes on. After setting
the new colors, Sopel will reply with a sample of the new colors, e.g.:
```
<@maxpowa> .help gh-hook-color
<Sopel> .gh-hook-color <repo> <repo color> <name color> <branch color> <tag color> <hash color> <url color>

<@maxpowa> .gh-hook-color maxpowa/Inumuta 13 15 6 6 14 2
<Sopel> [maxpowa/inumuta] Example name: maxpowa tag: tag commit: c0mm17 branch: master url: http://git.io/
<@maxpowa> Unfortunately, IRC colors don't show up on GitHub.
```
