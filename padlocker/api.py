#
#   Copyright 2013 Urban Airship
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import json
import netaddr
import sys
import os
import re

from flask import (
    Flask, abort, flash, redirect, request, render_template, url_for
)

from flask_login import LoginManager

import config
import dao
import user

app = Flask(__name__)
app.secret_key = 'funballs'
login_manager = LoginManager()
login_manager.init_app(app)

DAO = dao.RedisBackend(host='localhost', port=6379)

pad_config = config.PadConfig()

#
## Login stuff
###

@login_manager.user_loader
def load_user(userid):
    return user.User(userid)


def get_key_names():
    return [
        file for file in os.listdir(pad_config.key_dir)
        if not file.startswith('.')
    ]


def process_api_get():
    return json.dumps(get_key_names())


def apply_check(check, val):
    """This applies all checks configured for a given key."""
    retype = type(re.compile(""))
    functype = type(lambda x: x)

    if isinstance(check, str):
        sys.stdout.write("comparing '%s' and '%s' lexically..." % (check, val))
        if check == val:
            print "equal"
            return True

        else:
            print "not equal"
            return False

    elif isinstance(check, retype):
        sys.stdout.write("matching '%s' against regex '%s'..." % (
            val, check.pattern
        ))
        if check.match(val):
            print "matched"
            return True

        else:
            print "didn't match"
            return False

    elif isinstance(check, functype):
        sys.stdout.write("evaluating '%s' through lambda..." % val)
        if check(val):
            print "returned true"
            return True

        else:
            print "returned false"
            return False

    return True


def is_permitted(cn, req):
    key_config = pad_config.key_configs.get(cn)

    if not key_config:
        return False

    # ip check is manditory, as it's the only reliable metadata
    if not netaddr.all_matching_cidrs(
        request.remote_addr, key_config.get("cidr_ranges", ["0.0.0.0/32"])
    ):
        return False

    for check in key_config.keys():
        if check == 'cidr_ranges':
            continue
        if isinstance(key_config[check], list):
            for match in key_config[check]:
                if not apply_check(match, req.get(check, '')):
                    return False
        else:
            if not apply_check(key_config[check], req.get(check, '')):
                return False

    return True


def request_authorization(cn, key_req):
    """The request is permitted, but now we need approval to return the key."""

    ip = key_req.get('ip', '')
    DAO.enqueue_request(cn, ip, json.dumps({
        'cn': cn,
        'ip': request.remote_addr,
        'service': key_req.get('service', '')
    }))

    return 'Submitted, come back later', 201


def read_file(cn):
    with open('{0}/{1}'.format(pad_config.key_dir, cn)) as f:
        key_data = f.read()

    return key_data


def process_api_post(cn):
    try:
        key_req = json.loads(request.data)
    except:
        abort(400, 'you request contained invalid json')

    if not is_permitted(cn, key_req):
        abort(403, 'your request was denied')

    if cn in get_key_names():
        if DAO.is_authorized(cn, request.remote_addr):
            return read_file(cn)
        else:
            return request_authorization(cn, key_req)


def process_web_post():
    cn = request.form.get('cn')
    ip = request.form.get('ip')

    DAO.authorize_request(cn, ip)
    flash('You successfully approved {0}'.format(cn))

    return redirect(url_for('web_root'))


class Approval(object):
    """A context object for our webforms."""
    def __init__(self, *args, **kwargs):
        self.cn = kwargs.get('cn', '')
        self.ip = kwargs.get('ip', '')
        self.service = kwargs.get('service', '')
        payload = kwargs.get('payload', {})
        for item in payload:
            self.__setattr__(item, payload[item])


@app.route('/', methods=['GET', 'POST'])
def web_root():
    """Route that administrative users will use."""
    if request.method == 'POST':
        return process_web_post()

    auth_requests = [
        Approval(payload=auth_req) for auth_req in DAO.get_all_auth_requests()
    ]

    return render_template('index.html', auth_requests=auth_requests)


@app.route('/api/<cn>', methods=['POST'])
def get_cn(cn):
    return process_api_post(cn)

if __name__ == '__main__':
    app.debug = True
    app.run(host=pad_config.ip)
