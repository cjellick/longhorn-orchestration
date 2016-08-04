from common_fixtures import *  # NOQA
import os

vols_to_cleanup = []
cons_to_cleanup = []


def test_volume_basics(client):
    vol_name = random_str()

    c = client.create_container(imageUuid='docker:busybox:latest', tty=True,
                                StdinOpen=True, volumeDriver='longhorn',
                                dataVolumes=['%s:/zzz' % vol_name])
    c = wait_success(client, c)
    cons_to_cleanup.append(c)
    assert c.state == 'running'

    mounts = c.mounts()
    assert len(mounts) == 1
    vol = mounts[0].volume()
    vols_to_cleanup.append(vol)
    assert vol.state == 'active'
    assert vol.driver == 'longhorn'

    c = client.wait_success(c.stop())
    c = client.wait_success(c.remove())
    client.wait_success(c.purge())

    vol = client.wait_success(vol)
    vol = client.wait_success(vol.remove())
    vol = client.wait_success(vol.purge())
    assert vol.state == 'purged'


def test_snapshot_basics(client):
    vol_name = random_str()
    c = client.create_container(imageUuid='docker:busybox:latest',
                                tty=True, StdinOpen=True,
                                volumeDriver='longhorn',
                                dataVolumes=['%s:/zzz' % vol_name])
    cons_to_cleanup.append(c)
    c = wait_success(client, c)
    assert c.state == 'running'

    mounts = c.mounts()
    assert len(mounts) == 1
    vol = mounts[0].volume()
    vols_to_cleanup.append(vol)
    assert vol.state == 'active'
    assert vol.driver == 'longhorn'

    c = client.wait_success(c.stop())

    vol = client.wait_success(vol)
    snap = wait_success(client, vol.snapshot())
    assert snap.state == 'snapshotted'

    # Take a second snapshot so that we can delete the first
    snap2 = wait_success(client, vol.snapshot())
    assert snap2.state == 'snapshotted'

    snap = wait_success(client, snap.remove())
    assert snap.state == 'removed'

    vol = client.reload(vol)
    snaps = vol.snapshots()
    non_removed = [x for x in snaps if x.removed is None]
    assert len(non_removed) == 1
    final_snap = non_removed[0]

    vol = wait_success(client, vol.reverttosnapshot(snapshotId=final_snap.id))
    assert vol.state == 'active'

    # Even though we delete the vol in the finalizer, lets delete it as part of
    # the test because that will test deleting the one remaining snapshot
    c = client.wait_success(c.remove())
    client.wait_success(c.purge())
    vol = client.reload(vol)
    vol = client.wait_success(vol.remove())
    vol = client.wait_success(vol.purge())
    assert vol.state == 'purged'
    # TODO It doesnt actually do that yet
    # wait_for_condition(client, final_snap, lambda y: y.state == 'removed')


def test_backup_basics(client, backup_target):
    vol_name = random_str()
    c = client.create_container(imageUuid='docker:busybox:latest', tty=True,
                                StdinOpen=True, volumeDriver='longhorn',
                                dataVolumes=['%s:/zzz' % vol_name])
    cons_to_cleanup.append(c)
    c = wait_success(client, c)
    assert c.state == 'running'

    mounts = c.mounts()
    assert len(mounts) == 1
    vol = mounts[0].volume()
    vols_to_cleanup.append(vol)
    assert vol.state == 'active'
    assert vol.driver == 'longhorn'

    client.wait_success(c.stop())

    vol = client.wait_success(vol)
    snap = client.wait_success(vol.snapshot())
    assert snap.state == 'snapshotted'

    snaps = vol.snapshots()
    assert len(snaps) == 1

    snap = client.wait_success(snap.backup(backupTargetId=backup_target.id))
    assert snap.state == 'backedup'

    snap = client.wait_success(snap.removelocalsnapshot())
    vol = client.wait_success(vol.reverttosnapshot(snapshotId=snap.id))
    assert vol.state == 'active'


@pytest.fixture()
def backup_target(client):
    name = 'integration-tests-target'
    targets = client.list_backupTarget(name=name)
    config = nfs_config()
    target = None
    if len(targets) > 0:
        for t in targets:
            n = t.nfsConfig
            if n.server == config['server'] and n.share == config['share'] \
                    and n.mountOptions == config['mountOptions']:
                target = t
            else:
                t.remove()

    if not target:
        target = client.wait_success(
            client.create_backupTarget(name=name, nfsConfig=config))

    return target


def nfs_config():
    nfs_server = os.environ.get('NFS_SERVER')
    nfs_share = os.environ.get('NFS_SHARE')
    nfs_opts = os.environ.get('NFS_OPTS')
    if not nfs_config or not nfs_share:
        raise Exception('NFS server environment variables must be set.')

    return {
        'server': nfs_server,
        'share': nfs_share,
        'mountOptions': nfs_opts,
    }


@pytest.fixture(scope='module', autouse=True)
def cleanup_volumes(client, request):
    def fin():
        for i in [cons_to_cleanup, vols_to_cleanup]:
            for j in i:
                j = client.reload(j)
                if not j.removed:
                    try:
                        j = client.reload(j)
                        j = client.wait_success(j.stop())
                    except:
                        pass

                    try:
                        j = client.wait_success(j.remove())
                    except:
                        pass

                    try:
                        client.wait_success(j.purge())
                    except:
                        pass

    request.addfinalizer(fin)
