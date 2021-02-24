'''
Configures the esxi host for vSan.  This includes sorting found flash drives (only doing flash for now, no hybrid)
and then tagging/creating the "cache" and "capacity" disk groups
relies on vsanapituils.py and vsanmgmtObjects.py
hard coded variables for now that should change include vCenter, esxihost, vCenter pw
also, if vsan disks are already configured, then none will be found and program exits.
marcus_sharp 11/24/2020
'''

import atexit
import ssl
from pyVim import connect
from pyVmomi import vim
# import the VSAN API python bindings
# have to download these manually and extract from https://code.vmware.com/web/sdk/7.0%20U1/vsan-python
import vsanmgmtObjects
import vsanapiutils


def main():
    server = 'vcenter'
    si = vc_connect(server)
    atexit.register(connect.Disconnect, si)
    dc = si.content.rootFolder.childEntity[0]  # first datacenter
    content = si.RetrieveContent()
    esxihost = get_obj(content, [vim.HostSystem], 'esxi_host')
    if esxihost is None:
        print(f'Failed to find {esxihost}  in datacenter {dc.name}')
    else:
        # https://www.tachytelic.net/2014/03/posix-size-converter/
        # formula for bock to GB conversion = Number Of 512 byte blocks/2/1024/1024
        diskmap = {esxihost: {'cache': [], 'capacity': []}}
        cacheDisks = []
        capacityDisks = []
        result = esxihost.configManager.vsanSystem.QueryDisksForVsan()
        ssds = []
        for ssd in result:
            if ssd.state == 'eligible' and (ssd.disk.capacity.block) / 2 / 1024 / 1024 > 300:
                ssds.append(ssd.disk)
        # https://bit.ly/37lvGc3  vSAN SDKs Programming Guide
        if ssds:
            smallerSize = min([disk.capacity.block * disk.capacity.blockSize for disk in ssds])
            for ssd in ssds:
                size = ssd.capacity.block * ssd.capacity.blockSize
                if size == smallerSize:
                    diskmap[esxihost]['cache'].append(ssd)
                    cacheDisks.append((ssd.displayName, size, esxihost.name))
                else:
                    diskmap[esxihost]['capacity'].append(ssd)
                    capacityDisks.append((ssd.displayName, size, esxihost.name))

            for host, disks in diskmap.items():
                if disks['cache'] and disks['capacity']:
                    dm = vim.VimVsanHostDiskMappingCreationSpec(
                        cacheDisks=disks['cache'], capacityDisks=disks['capacity'],
                        creationType='allFlash',
                        host=host)
            # Execute the task
            tasks = []
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            # next two lines from https://github.com/storage-code/vsanDeploy/blob/master/vsanDeploy.py
            vcMos = vsanapiutils.GetVsanVcMos(si._stub, context=context)
            vsanVcDiskManagementSystem = vcMos['vsan-disk-management-system']
            task = vsanVcDiskManagementSystem.InitializeDiskMappings(dm)
            tasks.append(task)
            vsanapiutils.WaitForTasks(tasks, si)
        else:
            print('no disks to add')
            exit()


def get_obj(content, vimtype, name):
    obj = None
    container = content.viewManager.CreateContainerView(
        content.rootFolder, vimtype, True)
    for c in container.view:
        if c.name == name:
            obj = c
            break
    return obj


def vc_connect(vc):
    # Disabling SSL warnings
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    service_instance = None

    try:
        print(f'attempting to connect to {vc}')
        service_instance = connect.SmartConnect(host=vc,
                                                user='vcenter_admin_here',
                                                pwd='passwordhere',
                                                port=443,
                                                sslContext=context)

    except IOError as e:
        pass
    if not service_instance:
        raise SystemExit("Unable to connect to host with supplied info.")
    return service_instance


if __name__ == '__main__':
    main()
