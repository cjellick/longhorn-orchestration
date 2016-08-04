from cattle import from_env

import inspect
import os
import pytest
import random
import time

DEFAULT_TIMEOUT = 120


@pytest.fixture(scope='session')
def cattle_url():
    default_url = 'http://localhost:8080/v1/schemas'
    return os.environ.get('CATTLE_TEST_URL', default_url)


def _admin_client():
    access_key = os.environ.get("CATTLE_ACCESS_KEY", 'admin')
    secret_key = os.environ.get("CATTLE_SECRET_KEY", 'adminpass')
    return from_env(url=cattle_url(),
                    cache=False,
                    access_key=access_key,
                    secret_key=secret_key)


def _client_for_user(name, accounts):
    return from_env(url=cattle_url(),
                    cache=False,
                    access_key=accounts[name][0],
                    secret_key=accounts[name][1])


def create_user(admin_client, user_name, kind=None):
    if kind is None:
        kind = user_name

    password = user_name + 'pass'
    account = create_type_by_uuid(admin_client, 'account', user_name,
                                  kind=user_name,
                                  name=user_name)

    active_cred = None
    for cred in account.credentials():
        if cred.kind == 'apiKey' and cred.publicValue == user_name:
            active_cred = cred
            break

    if active_cred is None:
        active_cred = admin_client.create_api_key({
            'accountId': account.id,
            'publicValue': user_name,
            'secretValue': password
        })

    active_cred = wait_success(admin_client, active_cred)
    if active_cred.state != 'active':
        wait_success(admin_client, active_cred.activate())

    return [user_name, password, account]


def acc_id(client):
    obj = client.list_api_key()[0]
    return obj.account().id


def client_for_project(project):
    access_key = random_str()
    secret_key = random_str()
    admin_client = _admin_client()
    active_cred = None
    account = project
    for cred in account.credentials():
        if cred.kind == 'apiKey' and cred.publicValue == access_key:
            active_cred = cred
            break

    if active_cred is None:
        active_cred = admin_client.create_api_key({
            'accountId': account.id,
            'publicValue': access_key,
            'secretValue': secret_key
        })

    active_cred = wait_success(admin_client, active_cred)
    if active_cred.state != 'active':
        wait_success(admin_client, active_cred.activate())

    return from_env(url=cattle_url(),
                    cache=False,
                    access_key=access_key,
                    secret_key=secret_key)


def wait_success(client, obj, timeout=DEFAULT_TIMEOUT):
    return client.wait_success(obj, timeout=timeout)


def wait_for_condition(client, resource, check_function, fail_handler=None,
                       timeout=DEFAULT_TIMEOUT):
    sleep_time = _sleep_time()
    start = time.time()
    resource = client.reload(resource)
    while not check_function(resource):
        if time.time() - start > timeout:
            exception_msg = 'Timeout waiting for ' + resource.kind + \
                ' to satisfy condition: ' + \
                inspect.getsource(check_function)
            if fail_handler:
                exception_msg = exception_msg + fail_handler(resource)
            raise Exception(exception_msg)

        time.sleep(sleep_time.next())
        resource = client.reload(resource)

    return resource


def create_type_by_uuid(admin_client, type, uuid, activate=True, validate=True,
                        **kw):
    opts = dict(kw)
    opts['uuid'] = uuid

    objs = admin_client.list(type, uuid=uuid)
    obj = None
    if len(objs) == 0:
        obj = admin_client.create(type, **opts)
    else:
        obj = objs[0]

    obj = wait_success(admin_client, obj)
    if activate and obj.state == 'inactive':
        obj.activate()
        obj = wait_success(admin_client, obj)

    if validate:
        for k, v in opts.items():
            assert getattr(obj, k) == v

    return obj


@pytest.fixture(scope='session')
def accounts():
    result = {}
    admin_client = _admin_client()
    for user_name in ['admin', 'agent', 'user', 'agentRegister', 'test',
                      'readAdmin', 'token', 'superadmin', 'service']:
        result[user_name] = create_user(admin_client,
                                        user_name,
                                        kind=user_name)

    result['admin'] = create_user(admin_client, 'admin')
    system_account = admin_client.list_account(kind='system', uuid='system')[0]
    result['system'] = [None, None, system_account]

    return result


@pytest.fixture(scope='session')
def client(admin_client):
    client = client_for_project(
        admin_client.list_project(uuid="adminProject")[0])
    assert client.valid()
    return client


@pytest.fixture(scope='session')
def admin_client():
    admin_client = _admin_client()
    assert admin_client.valid()
    return admin_client


@pytest.fixture(scope='session')
def super_client(accounts):
    ret = _client_for_user('superadmin', accounts)
    return ret


@pytest.fixture
def random_str():
    return 'test-{0}'.format(random_num())


@pytest.fixture
def random_num():
    return random.randint(0, 1000000)


def _sleep_time():
    sleep = 0.01
    while True:
        yield sleep
        sleep *= 2
        if sleep > 1:
            sleep = 1


def default_value(name, default):
    result = os.environ.get('CATTLE_%s' % name, default)
    if result == '':
        return default
    return result
