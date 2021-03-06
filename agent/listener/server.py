#!/usr/bin/env python

from flask import Flask, render_template, redirect, request, url_for, jsonify, Response, session
import logging
import urllib2, urllib
import urllib2, urllib, urlparse
import urllib2, urllib
import ConfigParser
import os
import sys
import platform
import requests
from . import psapi
from . import pluginapi
import functools
import jinja2
import datetime
import re
from io import open

__VERSION__ = 1.5
__STARTED__ = datetime.datetime.now()


base_dir = os.path.dirname(sys.path[0])

#~ The following if statement is a workaround that is allowing us to run this in debug mode, rather than a hard coded
#~ location.

if os.name == u'nt':
    tmpl_dir = os.path.join(base_dir, u'listener', u'templates')
    if not os.path.isdir(tmpl_dir):
        tmpl_dir = os.path.join(base_dir, u'agent', u'listener', u'templates')

    stat_dir = os.path.join(base_dir, u'listener', u'static')
    if not os.path.isdir(stat_dir):
        stat_dir = os.path.join(base_dir, u'agent', u'listener', u'static')

    logging.info(u"Looking for templates at: %s" % tmpl_dir)
    listener = Flask(__name__, template_folder=tmpl_dir, static_folder=stat_dir)
    listener.jinja_loader = jinja2.FileSystemLoader(tmpl_dir)
else:
    tmpl_dir = os.path.join(base_dir, u'agent', u'listener', u'templates')
    if not os.path.isdir(tmpl_dir):
        tmpl_dir = os.path.join(u'/usr', u'local', u'ncpa', u'listener', u'templates')

    stat_dir = os.path.join(base_dir, u'agent', u'listener', u'static')
    if not os.path.isdir(stat_dir):
        stat_dir = os.path.join(u'/usr', u'local', u'ncpa', u'listener', u'static')

    listener = Flask(__name__, template_folder=tmpl_dir, static_folder=stat_dir)

listener.jinja_env.line_statement_prefix = u'#'


def requires_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        ncpa_token = listener.config[u'iconfig'].get(u'api', u'community_string')
        token = request.args.get(u'token', None)

        if session.get(u'logged', False):
            pass
        elif token is None:
            return redirect(url_for(u'login'))
        elif token != ncpa_token:
            return error(msg=u'Incorrect credentials given.')
        return f(*args, **kwargs)

    return decorated


@listener.route(u'/login', methods=[u'GET', u'POST'])
def login():
    ncpa_token = listener.config[u'iconfig'].get(u'api', u'community_string')

    if request.method == u'GET':
        token = request.args.get(u'token', None)
    elif request.method == u'POST':
        token = request.form.get(u'token', None)
    else:
        token = None

    if token is None:
        return render_template(u'login.html')
    if token == ncpa_token:
        session[u'logged'] = True
        return redirect(url_for(u'index'))
    if token != ncpa_token:
        return render_template(u'login.html', error=u'Token was invalid.')


@listener.route(u'/dashboard')
@requires_auth
def dashboard():
    my_json = api(u'disk/logical', raw=True)
    disks = [{u'safe': re.sub(ur'[^a-zA-Z0-9]', u'', x),
              u'raw': x} for x in list(my_json.get(u'logical').keys())]
    my_json = api(u'interface/', raw=True)
    interfaces = [{u'safe': re.sub(ur'[^a-zA-Z0-9]', u'', x),
                   u'raw': x} for x in list(my_json.get(u'interface').keys())]
    my_json = api(u'cpu/count', raw=True)
    cpu_count = my_json.get(u'count', 0)

    return render_template(u'dashboard.html',
                           disks=disks,
                           interfaces=interfaces,
                           cpucount=cpu_count)


@listener.route(u'/navigator')
@requires_auth
def navigator():
    return render_template(u'navigator.html')


@listener.route(u'/config', methods=[u'GET', u'POST'])
@requires_auth
def config():
    if request.method == u'POST':
        new_config = save_config(request.form, listener.config_filename)
        listener.config[u'iconfig'] = new_config
        config_fp = open(listener.config_filename, u'w')
        new_config.write(config_fp)
        config_fp.close()

    section = request.args.get(u'section')
    if section:
        try:
            return jsonify(**listener.config[u'iconfig'].__dict__[u'_sections'][section])
        except Exception, e:
            logging.exception(e)
    return render_template(u'config.html', **{u'config': listener.config[u'iconfig'].__dict__[u'_sections']})


@listener.route(u'/logout')
def logout():
    if session.get(u'logged', False):
        session[u'logged'] = False
        return render_template(u'login.html', info=u'Successfully logged out.')
    else:
        return redirect(url_for(u'login'))


def make_info_dict():
    global __VERSION__
    global __STARTED__

    now = datetime.datetime.now()
    uptime = unicode(now - __STARTED__)

    return {u'agent_version': __VERSION__,
            u'uptime': uptime,
            u'processor': platform.uname()[5],
            u'node': platform.uname()[1],
            u'system': platform.uname()[0],
            u'release': platform.uname()[2],
            u'version': platform.uname()[3]}


@listener.route(u'/')
@requires_auth
def index():
    info = make_info_dict()
    try:
        return render_template(u'main.html', **info)
    except Exception, e:
        logging.exception(e)


@listener.route(u'/error/')
@listener.route(u'/error/<msg>')
def error(msg=None):
    if not msg:
        msg = u'Error occurred during processing request.'
    return jsonify(error=msg)


@listener.route(u'/testconnect/')
def testconnect():
    ncpa_token = listener.config[u'iconfig'].get(u'api', u'community_string')
    token = request.args.get(u'token', None)
    if ncpa_token != token:
        return jsonify({u'error': u'Bad token.'})
    else:
        return jsonify({u'value': u'Success.'})


@listener.route(u'/nrdp/', methods=[u'GET', u'POST'])
def nrdp():
    try:
        forward_to = listener.config[u'iconfig'].get(u'nrdp', u'parent')
        if request.method == u'get':
            response = requests.get(forward_to, params=request.args)
        else:
            response = requests.post(forward_to, params=request.form)
        resp = Response(response.content, 200, mimetype=response.headers[u'content-type'])
        return resp
    except Exception, e:
        logging.exception(e)
        return error(msg=unicode(e))


@listener.route(u'/api/agent/plugin/<plugin_name>/')
@listener.route(u'/api/agent/plugin/<plugin_name>/<path:plugin_args>')
@requires_auth
def plugin_api(plugin_name=None, plugin_args=None):
    config = listener.config[u'iconfig']
    if plugin_args:
        logging.info(plugin_args)
        plugin_args = [urllib.unquote(x) for x in plugin_args.split(u'/')]
    try:
        response = pluginapi.execute_plugin(plugin_name, plugin_args, config)
    except Exception, e:
        logging.exception(e)
        return error(msg=u'Error running plugin: %s' % unicode(e))
    return jsonify({u'value': response})


@listener.route(u'/api/')
@listener.route(u'/api/<path:accessor>')
@requires_auth
def api(accessor=u'', raw=False):
    if request.args.get(u'check'):
        url = accessor + u'?' + urllib.urlencode(request.args)
        return jsonify({u'value': internal_api(url, listener.config[u'iconfig'])})
    try:
        response = psapi.getter(accessor, listener.config[u'iconfig'].get(u'plugin directives', u'plugin_path'))
    except Exception, e:
        logging.exception(e)
        return error(msg=u'Referencing node that does not exist.')
    if raw:
        return response
    else:
        return jsonify({u'value': response})


def internal_api(accessor=None, listener_config=None):
    logging.debug(u'Accessing internal API with accessor %s', accessor)
    accessor_name, accessor_args, plugin_name, plugin_args = parse_internal_input(accessor)
    if accessor_name:
        try:
            logging.debug(u'Accessing internal API with accessor %s', accessor_name)
            acc_response = psapi.getter(accessor_name)
        except IndexError, e:
            logging.exception(e)
            logging.warning(u"User request invalid node: %s" % accessor_name)
            result = {u'returncode': 3, u'stdout': u'Invalid entry specified. No known node by %s' % accessor_name}
        else:
            result = pluginapi.make_plugin_response_from_accessor(acc_response, accessor_args)
    elif plugin_name:
        result = pluginapi.execute_plugin(plugin_name, plugin_args, listener_config)
    else:
        result = {u'stdout': u'ERROR: Non-node value requested. Requested a tree.', 
                  u'returncode': 3}
    return result


def save_config(dconfig, writeto):
    viv = vivicate_dict(dconfig)
    config = ConfigParser.ConfigParser()

    #~ Do the normal sections
    for s in [u'listener', u'passive', u'nrdp', u'nrds', u'api']:
        config.add_section(s)
        for t in viv[s]:
            config.set(s, t, viv[s][t])

    #~ Do the plugin directives
    directives = viv[u'directives']
    config.add_section(u'plugin directives')

    config.set(u'plugin directives', u'plugin_path', directives[u'plugin_path'])
    del directives[u'plugin_path']

    dkeys = [x for x in list(directives.keys()) if u'suffix|' in x]
    for x in dkeys:
        _, suffix = x.split(u'|')
        config.set(u'plugin directives', suffix, directives[u'exec|' + suffix])

    pchecks = viv[u'passivecheck']
    config.add_section(u'passive checks')

    pkeys = [x for x in list(pchecks.keys()) if u'name|' in x]
    for x in pkeys:
        _, pid = x.split(u'name|', 1)
        config.set(u'passive checks', pchecks[x], pchecks[u'exec|' + pid])

    return config


def vivicate_dict(d, delimiter=u'|'):
    result = {}
    for x in d:
        if delimiter in x:
            key, value = x.split(delimiter, 1)
            if key in result:
                result[key][value] = d[x]
            else:
                result[key] = {value: d[x]}
        else:
            result[x] = d[x]

    return result


def parse_internal_input(accessor):
    ACCESSOR_REGEX = re.compile(u'(/api)?/?([^?]+)\??(.*)')
    PLUGIN_REGEX = re.compile(u'(/api)?(/?agent/)?plugin/([^/]+)(/(.*))?')

    accessor_name = None
    accessor_args = None
    plugin_name = None
    plugin_args = None

    plugin_result = PLUGIN_REGEX.match(accessor)
    accessor_result = ACCESSOR_REGEX.match(accessor)

    if plugin_result:
        logging.debug(u'Plugin result!')
        plugin_name = plugin_result.group(3)
        plugin_args = plugin_result.group(5)
    elif accessor_result:
        logging.debug(u'Accessor result!')
        accessor_name = accessor_result.group(2)
        accessor_args = accessor_result.group(3)
    return accessor_name, accessor_args, plugin_name, plugin_args
